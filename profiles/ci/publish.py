import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile


PROFILES = Path(__file__).resolve().parents[1]
CONTROL = PROFILES.parent
CONFIG = json.loads((PROFILES / "publish.json").read_text(encoding="utf-8"))
COMPONENTS = ("ffmpegkit", "libavcodec", "libavdevice", "libavfilter", "libavformat",
              "libavutil", "libswresample", "libswscale")


def run(arguments, cwd=None, capture=False, check=True, env=None, timeout=None):
    result = subprocess.run(list(map(str, arguments)), cwd=cwd or CONTROL, env=env,
                            text=True, encoding="utf-8", check=check,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, timeout=timeout)
    return result


def git(source, *arguments):
    return run(["git", *arguments], cwd=source, capture=True).stdout.strip()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_plan(dist):
    plan = json.loads((dist / "plan.json").read_text(encoding="utf-8"))
    if plan["inputs"] != inputs():
        raise ValueError("Release tooling/configuration changed after planning")
    if plan["control_sha"] != git(CONTROL, "rev-parse", "HEAD"):
        raise ValueError("Release tooling checkout differs from the planned commit")
    return plan


def inputs():
    paths = [PROFILES / "publish.json", *sorted((PROFILES / "ci").rglob("*.py")),
             PROFILES / "ci/setup-windows.sh", PROFILES / "ci/dispatch.yml",
             CONTROL / ".github/workflows/publish-studio.yml", *[PROFILES / p for p in CONFIG["patches"]]]
    return {path.relative_to(CONTROL).as_posix(): digest(path) for path in paths}


def remote_tag(repository, tag):
    result = run(["gh", "api", f"repos/{repository}/git/ref/tags/{tag}"], capture=True, check=False)
    if result.returncode == 0:
        return True
    try:
        missing = str(json.loads(result.stdout).get("status")) == "404"
    except (ValueError, TypeError):
        missing = False
    if missing and "HTTP 404" in result.stderr:
        return False
    raise ValueError(f"Cannot check remote tag: {result.stderr}")


def api(path, raw=False):
    arguments = ["gh", "api", path]
    if raw:
        arguments += ["-H", "Accept: application/vnd.github.raw+json"]
    output = run(arguments, capture=True).stdout
    return output if raw else json.loads(output)


def plan_release(upstream_tag, number, dist):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", upstream_tag) or number < 0:
        raise ValueError("Use an upstream vMAJOR.MINOR.PATCH tag and a nonnegative build number (0 selects the next available number)")
    if (dist / "plan.json").exists():
        raise ValueError("Use an empty output directory for a new release")
    if number == 0:
        tags = api(f"repos/{CONFIG['repository']}/git/matching-refs/tags/{upstream_tag}-studio.")
        numbers = [int(match.group(1)) for item in tags
                   if (match := re.fullmatch(re.escape(f"refs/tags/{upstream_tag}-studio.") + r"(\d+)", item["ref"]))]
        number = max(numbers, default=0) + 1
    tag = f"{upstream_tag}-studio.{number}"
    if remote_tag(CONFIG["repository"], tag):
        raise ValueError(f"{tag} already exists; choose the next build number")
    upstream_sha = api(f"repos/{CONFIG['upstream']}/commits/{upstream_tag}")["sha"]
    recipe = api(f"repos/{CONFIG['upstream']}/contents/scripts/source.sh?ref={upstream_sha}", raw=True)
    match = re.search(r"(?m)^\s*ffmpeg\)\s*\n(.*?)(?=;;)", recipe, re.S)
    source_id = re.search(r'SOURCE_ID="([^"]+)"', match.group(1)).group(1) if match else None
    if not source_id or not re.fullmatch(r"n\d+\.\d+(?:\.\d+)?", source_id):
        raise ValueError("Upstream FFmpeg source tag needs manual review")
    ffmpeg_sha = api(f"repos/arthenica/FFmpeg/commits/{source_id}")["sha"]
    pubspec = api(f"repos/{CONFIG['upstream']}/contents/flutter/flutter/pubspec.yaml?ref={upstream_sha}", raw=True)
    version = re.search(r"(?m)^version:\s*(\S+)", pubspec).group(1)
    if version != upstream_tag[1:]:
        raise ValueError("Upstream tag and Flutter plugin version disagree")
    plan = {"upstream_tag": upstream_tag, "upstream_sha": upstream_sha,
            "release_tag": tag, "wrapper_version": version,
            "ffmpeg_tag": source_id, "ffmpeg_sha": ffmpeg_sha,
            "control_sha": git(CONTROL, "rev-parse", "HEAD"), "inputs": inputs()}
    save(dist / "plan.json", plan)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for key in ("control_sha", "upstream_sha", "release_tag"):
                stream.write(f"{key}={plan[key]}\n")
    print(json.dumps(plan, indent=2))


def prepare(source, plan):
    if git(source, "rev-parse", "HEAD") != plan["upstream_sha"]:
        raise ValueError("Source checkout differs from the pinned upstream commit")
    if git(source, "status", "--porcelain"):
        raise ValueError("Prepare requires a clean upstream checkout")
    for relative in CONFIG["patches"]:
        patch = PROFILES / relative
        reverse = run(["git", "apply", "--reverse", "--check", patch], cwd=source,
                      capture=True, check=False)
        if reverse.returncode == 0:
            print(f"Already upstream: {relative}")
        else:
            result = run(["git", "apply", "--check", patch], cwd=source, capture=True, check=False)
            if result.returncode:
                raise ValueError(f"Review/rebase {relative} for this tag:\n{result.stderr}")
            run(["git", "apply", patch], cwd=source)
    run(["git", "add", "-A"], cwd=source)
    return {"plan": plan, "prepared_tree": git(source, "write-tree")}


def manifest(root):
    entries = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Bundle link escapes its root: {name}")
            entries[name] = {"link": target}
        elif path.is_file():
            entries[name] = {"sha256": digest(path), "size": path.stat().st_size,
                             "executable": bool(path.stat().st_mode & 0o100)}
    if not entries:
        raise ValueError("Native bundle is empty")
    return entries


def validate_binaries(root, platform, version):
    if platform == "windows":
        for relative in ("include/ffmpegkit_c.h", "lib/ffmpegkit.lib", "licenses/license.txt"):
            if not (root / relative).is_file():
                raise ValueError(f"Missing Windows file: {relative}")
        for component in COMPONENTS:
            matches = list((root / "bin").glob(f"*{component.removeprefix('lib')}-*.dll"))
            if len(matches) != 1:
                raise ValueError(f"Missing/ambiguous Windows DLL: {component}")
            data = matches[0].read_bytes()
            offset = struct.unpack_from("<I", data, 0x3c)[0]
            if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
                raise ValueError("Windows bundle must contain x64 DLLs")
        config = (root / "lib/cmake/ffmpeg-kit-next/ffmpeg-kit-next-config.cmake").read_text()
        if f'FFMPEG_KIT_NEXT_VERSION "{version}"' not in config:
            raise ValueError("Windows wrapper version differs from the release")
    elif platform == "android":
        aar = root / f"com/arthenica/ffmpeg-kit-next/{version}/ffmpeg-kit-next-{version}.aar"
        with zipfile.ZipFile(aar) as archive:
            for abi, library in (("armeabi-v7a", "libffmpegkit_armv7a_neon.so"),
                                 ("arm64-v8a", "libffmpegkit.so"), ("x86_64", "libffmpegkit.so")):
                if f"jni/{abi}/{library}" not in archive.namelist():
                    raise ValueError(f"Android bundle is missing {abi}")
    else:
        required = ({("ios", "", "arm64"), ("ios", "simulator", "arm64"),
                     ("ios", "simulator", "x86_64")} if platform == "ios" else
                    {("macos", "", "arm64"), ("macos", "", "x86_64")})
        for component in COMPONENTS:
            framework = root / f"{component}.xcframework"
            libraries = plistlib.loads((framework / "Info.plist").read_bytes())["AvailableLibraries"]
            found = {(item["SupportedPlatform"], item.get("SupportedPlatformVariant", ""), arch)
                     for item in libraries for arch in item["SupportedArchitectures"]}
            if not required.issubset(found):
                raise ValueError(f"Missing {platform} architectures: {component}")
            if component == "ffmpegkit":
                for item in libraries:
                    inner = framework / item["LibraryIdentifier"] / item["LibraryPath"]
                    plists = list(inner.rglob("Info.plist"))
                    if not plists or any(plistlib.loads(p.read_bytes()).get("CFBundleShortVersionString") != version for p in plists):
                        raise ValueError("Apple wrapper version differs from the release")


def bash(source, arguments, shell):
    env = dict(os.environ)
    if sys.platform == "win32":
        if not shell:
            raise ValueError("Pass the MSYS2 bash executable with --bash")
        env.update(MSYSTEM="CLANG64", CHERE_INVOKING="1")
        converted = run([shell, "-c", 'cygpath -u "$1"', "publish", source], env=env, capture=True).stdout.strip()
        run([shell, "-lc", "cd " + shlex.quote(converted) + " && " + shlex.join(arguments)], env=env)
    else:
        run(["bash", *arguments], cwd=source, env=env)


def build(source, dist, platform, shell):
    plan = read_plan(dist)
    identity = prepare(source, plan)
    entry = CONFIG["platforms"][platform]
    bash(source, ["./" + entry["script"], *CONFIG["common_args"],
                  "--lib-version-ffmpeg=" + plan["ffmpeg_tag"], *entry["args"]], shell)
    if git(source / "src/ffmpeg", "rev-parse", "HEAD") != plan["ffmpeg_sha"]:
        raise ValueError("FFmpeg source tag changed or build used a different commit")
    bash(source, ["flutter/flutter/copy_local_binaries.sh", platform], shell)
    root = source / entry["binary_path"]
    validate_binaries(root, platform, plan["wrapper_version"])
    if platform in ("windows", "macos"):
        run([sys.executable, PROFILES / "ci/smoke.py", root, platform,
             plan["wrapper_version"], plan["ffmpeg_tag"]], cwd=source, timeout=180)
    receipt = {"identity": identity, "platform": platform, "files": manifest(root)}
    receipt_file = dist / f"{platform}.json"
    save(receipt_file, receipt)
    archive = dist / f"{plan['release_tag']}-{platform}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(root, arcname=entry["binary_path"])
        bundle.add(receipt_file, arcname="manifest.json")
    archive.with_suffix(archive.suffix + ".sha256").write_text(digest(archive) + "  " + archive.name + "\n")


def import_bundle(archive, source, identity, platform):
    expected = archive.with_suffix(archive.suffix + ".sha256").read_text().split()[0]
    if digest(archive) != expected:
        raise ValueError(f"Archive checksum mismatch: {platform}")
    prefix = CONFIG["platforms"][platform]["binary_path"]
    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            if len(names) != len(set(names)) or names.count("manifest.json") != 1:
                raise ValueError("Duplicate archive members or missing manifest")
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                    raise ValueError("Unsafe archive path")
                if member.name != "manifest.json" and member.name != prefix and not member.name.startswith(prefix + "/"):
                    raise ValueError("Unexpected archive member")
                if not (member.isfile() or member.isdir() or member.issym()):
                    raise ValueError("Unsupported archive member")
            bundle.extractall(staging, filter="data")
        receipt = json.loads((staging / "manifest.json").read_text())
        if receipt["identity"] != identity or receipt["platform"] != platform:
            raise ValueError(f"Different source/tooling in {platform} artifact")
        if manifest(staging / prefix) != receipt["files"]:
            raise ValueError(f"Native bundle was modified: {platform}")
        validate_binaries(staging / prefix, platform, identity["plan"]["wrapper_version"])
        destination = source / prefix
        if destination.exists():
            raise ValueError("Assembly needs a fresh checkout without existing binaries")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging / prefix, destination, symlinks=True)
    return receipt


def assemble(source, dist):
    plan = read_plan(dist)
    identity = prepare(source, plan)
    receipts = {}
    for platform in CONFIG["platforms"]:
        archive = dist / f"{plan['release_tag']}-{platform}.tar.gz"
        receipts[platform] = import_bundle(archive, source, identity, platform)
    for relative in ("profiles/publish.json", "profiles/ci", ".github/workflows/publish-studio.yml"):
        destination = source / relative
        if destination.exists():
            raise ValueError(f"Upstream now contains {relative}; review before overwriting it")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (CONTROL / relative).is_dir():
            shutil.copytree(CONTROL / relative, destination, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(CONTROL / relative, destination)
    for relative in CONFIG["patches"]:
        destination = source / "profiles" / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROFILES / relative, destination)
    provenance = {"identity": identity,
                  "build_flags": {name: [*CONFIG["common_args"], "--lib-version-ffmpeg=" + plan["ffmpeg_tag"], *entry["args"]]
                                  for name, entry in CONFIG["platforms"].items()},
                  "bundles": {name: {"files": receipt["files"]} for name, receipt in receipts.items()}}
    save(source / "release-build.json", provenance)
    paths = [entry["binary_path"] for entry in CONFIG["platforms"].values()]
    for receipt in receipts.values():
        if any(details.get("size", 0) >= 100 * 1024 * 1024 for details in receipt["files"].values()):
            raise ValueError("A binary exceeds GitHub's Git file size limit")
    run(["git", "add", "-f", "--", *paths, "profiles", "release-build.json",
         ".github/workflows/publish-studio.yml"], cwd=source)
    for platform, receipt in receipts.items():
        prefix = CONFIG["platforms"][platform]["binary_path"]
        executable = [prefix + "/" + name for name, item in receipt["files"].items()
                      if item.get("executable")]
        if executable:
            run(["git", "update-index", "--chmod=+x", "--", *executable], cwd=source)
    os.environ.update(GIT_AUTHOR_NAME="github-actions[bot]", GIT_COMMITTER_NAME="github-actions[bot]",
                      GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
                      GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    git(source, "commit", "-m", f"release: {plan['release_tag']} (FFmpeg {plan['ffmpeg_tag'].removeprefix('n')}, Studio, four platforms)",
        "-m", f"Package native binaries from {plan['upstream_tag']} with the Studio profile.",
        "-m", "Record pinned sources, build flags and binary hashes in release-build.json.")
    annotation = (f"{plan['release_tag']}\n\nFFmpeg {plan['ffmpeg_tag']}; source {plan['upstream_sha']}\n"
                  f"Release tooling {plan['control_sha']}\n\n" +
                  "\n".join(f"{name}: " + shlex.join(flags) for name, flags in provenance["build_flags"].items()))
    git(source, "tag", "-a", plan["release_tag"], "-m", annotation)
    run(["git", "bundle", "create", str(dist / "release.bundle"), f"refs/tags/{plan['release_tag']}"], cwd=source)
    notes = (f"Studio native binaries based on [{plan['upstream_tag']}]"
             f"(https://github.com/{CONFIG['upstream']}/tree/{plan['upstream_sha']}).\n\n"
             f"FFmpeg: `{plan['ffmpeg_tag']}` (`{plan['ffmpeg_sha']}`).\n\n"
             "Android (3 ABIs), iOS (device + 2 simulator architectures), macOS universal, Windows x64.\n\n"
             "GPL enabled. Libraries: x264, x265, dav1d, LAME, zimg, zlib and libiconv; "
             "Apple also enables bzip2/VideoToolbox, Android enables MediaCodec.\n\n"
             "Local patches: Clang 22 Windows colorspace/blur workarounds and Apple Flutter null options.\n\n"
             "Windows and macOS native smoke checks passed. Android/iOS bundles were structurally "
             "validated; this workflow does not run Android/iOS applications.\n\n"
             "Use the tagged Flutter Git dependency at `flutter/flutter`. Android applications must "
             "register the plugin's `libs-maven` repository as documented in `flutter/flutter/BUILD.md`.\n\n"
             "Build flags, source/patch identity and file hashes are recorded in `release-build.json`.\n")
    (dist / "RELEASE-NOTES.md").write_text(notes, encoding="utf-8")


def publish(source, dist, mode):
    plan = read_plan(dist)
    tag = plan["release_tag"]
    repository = CONFIG["repository"]
    if os.environ.get("GITHUB_REPOSITORY") != repository:
        raise ValueError("Publishing is restricted to the configured fork")
    if git(source, "status", "--porcelain"):
        raise ValueError("Publishing requires the clean assembled release checkout")
    if git(source, "rev-parse", f"refs/tags/{tag}^{{commit}}") != git(source, "rev-parse", "HEAD"):
        raise ValueError("Local release tag does not point to the assembled commit")
    assets = [str(dist / f"{tag}-{platform}{suffix}") for platform in CONFIG["platforms"]
              for suffix in (".tar.gz", ".tar.gz.sha256")]
    if not all(Path(path).is_file() for path in assets):
        raise ValueError("Release assets are incomplete")
    if remote_tag(repository, tag):
        git(source, "fetch", "--no-tags", f"https://github.com/{repository}.git", f"refs/tags/{tag}")
        if git(source, "rev-parse", "FETCH_HEAD^{tree}") != git(source, "rev-parse", "HEAD^{tree}"):
            raise ValueError("Remote tag has different content; it will never be overwritten")
    else:
        git(source, "push", f"https://github.com/{repository}.git", f"refs/tags/{tag}")
    result = run(["gh", "release", "view", tag, "--repo", repository, "--json", "isDraft"],
                 capture=True, check=False)
    if result.returncode == 0:
        if not json.loads(result.stdout)["isDraft"]:
            if mode == "publish":
                print("Matching release is already published")
                return
            raise ValueError("Existing published release cannot be changed back to a draft")
        run(["gh", "release", "upload", tag, "--repo", repository, "--clobber", *assets])
    else:
        run(["gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--draft",
             "--title", tag, "--notes-file", dist / "RELEASE-NOTES.md", *assets])
    if mode == "publish":
        run(["gh", "release", "edit", tag, "--repo", repository, "--draft=false"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "build", "assemble", "publish"))
    parser.add_argument("--source", type=Path, default=CONTROL / "source")
    parser.add_argument("--dist", type=Path, default=CONTROL / "dist")
    parser.add_argument("--upstream-tag", default="v9.0.2")
    parser.add_argument("--number", type=int, default=0)
    parser.add_argument("--platform", choices=CONFIG["platforms"])
    parser.add_argument("--bash")
    parser.add_argument("--mode", choices=("draft", "publish"), default="draft")
    args = parser.parse_args()
    source, dist = args.source.resolve(), args.dist.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    if args.command == "plan":
        plan_release(args.upstream_tag, args.number, dist)
    elif args.command == "build":
        if not args.platform:
            parser.error("build requires --platform")
        build(source, dist, args.platform, args.bash)
    elif args.command == "assemble":
        assemble(source, dist)
    else:
        publish(source, dist, args.mode)


if __name__ == "__main__":
    main()
