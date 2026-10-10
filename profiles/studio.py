#!/usr/bin/env python3
import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import platform
import shlex
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONFIG = json.loads((HERE / "studio.json").read_text(encoding="utf-8"))
DIST = REPO / "prebuilt/studio-release"


def run(args, *, capture=False, env=None, cwd=None):
    print("+ " + shlex.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), cwd=cwd or REPO, env=env,
                          check=True, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE if capture else None).stdout


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identity():
    profile = (HERE / "studio.sh").read_text(encoding="utf-8")
    arrays = {name: shlex.split(values) for name, values in re.findall(r"(\w+)=\((.*?)\)", profile, re.S)}
    if set(arrays.get("platforms", [])) != set(CONFIG["platforms"]):
        raise ValueError("Studio platform list differs from the audited configuration")
    for name, entry in CONFIG["platforms"].items():
        if arrays.get(name + "_args") != [*CONFIG["common_args"], *entry["args"]]:
            raise ValueError(f"Studio {name} flags differ from the audited configuration")
    return {"base_commit": CONFIG["base_commit"],
            "ffmpeg_source": CONFIG["ffmpeg_source"],
            "ffmpeg_commit": CONFIG["ffmpeg_commit"],
            "wrapper_version": CONFIG["wrapper_version"],
            "profile_sha256": digest(HERE / "studio.json"),
            "flags_sha256": digest(HERE / "studio.sh"),
            "builder_sha256": digest(HERE / "studio.py"),
            "patched_tree": CONFIG["patched_tree"],
            "patch_sha256": {item["file"]: digest(HERE / item["file"]) for item in CONFIG["patches"]}}


def check_source():
    head = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    if head == CONFIG["base_commit"]:
        return
    run(["git", "merge-base", "--is-ancestor", CONFIG["base_commit"], head], capture=True)
    tree = source_tree()
    changed = run(["git", "diff", "--name-only", tree, head], capture=True).splitlines()
    unexpected = [path for path in changed if path not in (".gitignore", ".gitattributes")
                  and not path.startswith("profiles/")]
    if unexpected:
        raise ValueError(f"Source differs from the audited Studio tree: {unexpected}")


def source_tree():
    with tempfile.TemporaryDirectory() as folder:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / "index"))
        run(["git", "read-tree", CONFIG["base_commit"]], env=env, capture=True)
        for item in CONFIG["patches"]:
            run(["git", "apply", "--cached", HERE / item["file"]], env=env, capture=True)
        tree = run(["git", "write-tree"], env=env, capture=True).strip()
    if tree != CONFIG["patched_tree"]:
        raise ValueError("Stable patch set changed; re-review and rebuild all platforms")
    return tree


def prepare_source():
    tree = source_tree()
    paths = run(["git", "diff", "--name-only", CONFIG["base_commit"], tree], capture=True).splitlines()
    base_files = set(run(["git", "ls-tree", "-r", "--name-only", CONFIG["base_commit"]], capture=True).splitlines())
    writes = []
    for relative in paths:
        expected = run(["git", "show", tree + ":" + relative], capture=True)
        original = run(["git", "show", CONFIG["base_commit"] + ":" + relative], capture=True) if relative in base_files else None
        destination = REPO / relative
        current = destination.read_text(encoding="utf-8") if destination.exists() else None
        allowed = [original, expected]
        # The upstream Windows native recipe disables the host-process argv path.
        if relative in ("windows/src/fftools/cmdutils.c", "windows/src/fftools/cmdutils.h"):
            allowed.append(expected.replace("#if HAVE_COMMANDLINETOARGVW && defined(_WIN32)",
                                            "#if 0 && HAVE_COMMANDLINETOARGVW && defined(_WIN32)"))
        if current not in allowed:
            raise ValueError(f"Unexpected local changes to stable patch file: {relative}")
        if current != expected:
            writes.append((destination, expected))
    for destination, expected in writes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(expected, encoding="utf-8", newline="\n")
    return tree


def files_manifest(root, binary_path):
    result = {}
    base = root / binary_path
    if not base.is_dir():
        raise ValueError(f"Missing binaries: {base}")
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(base.resolve()):
                raise ValueError(f"Symlink escapes binary directory: {relative}")
            result[relative] = {"link": os.readlink(path)}
        elif path.is_file():
            result[relative] = {"sha256": digest(path), "size": path.stat().st_size}
    if not result:
        raise ValueError("Empty binary bundle")
    return result


def check_binaries(root, name):
    base = root / CONFIG["platforms"][name]["binary_path"]
    version = CONFIG["wrapper_version"]
    if name == "windows":
        for item in ["include/ffmpegkit_c.h", "lib/ffmpegkit.lib",
                     "lib/cmake/ffmpeg-kit-next/ffmpeg-kit-next-config.cmake"]:
            if not (base / item).is_file():
                raise ValueError(f"Missing Windows {item}")
        text = (base / "lib/cmake/ffmpeg-kit-next/ffmpeg-kit-next-config.cmake").read_text()
        if f'FFMPEG_KIT_NEXT_VERSION "{version}"' not in text or 'FFMPEG_KIT_NEXT_ARCHITECTURE "x64"' not in text:
            raise ValueError("Wrong Windows version/architecture")
        for component in ["avcodec", "avdevice", "avfilter", "avformat", "avutil", "swresample", "swscale", "ffmpegkit"]:
            if not list((base / "bin").glob(f"*{component}-*.dll")):
                raise ValueError(f"Missing DLL: {component}")
        if not (base / "licenses/license.txt").is_file():
            raise ValueError("Missing Windows bundle licenses")
    elif name == "android":
        aar = base / f"com/arthenica/ffmpeg-kit-next/{version}/ffmpeg-kit-next-{version}.aar"
        with zipfile.ZipFile(aar) as bundle:
            for abi in ["armeabi-v7a", "arm64-v8a", "x86_64"]:
                if f"jni/{abi}/libffmpegkit.so" not in bundle.namelist():
                    raise ValueError(f"Missing Android ABI {abi}")
    else:
        for component in ["ffmpegkit", "libavcodec", "libavdevice", "libavfilter", "libavformat", "libavutil", "libswresample", "libswscale"]:
            framework = base / f"{component}.xcframework"
            with (framework / "Info.plist").open("rb") as source:
                slices = plistlib.load(source)["AvailableLibraries"]
            if name == "ios":
                required = {("ios", "", "arm64"), ("ios", "simulator", "arm64"), ("ios", "simulator", "x86_64")}
            else:
                required = {("macos", "", "arm64"), ("macos", "", "x86_64")}
            found = {(item["SupportedPlatform"], item.get("SupportedPlatformVariant", ""), arch)
                     for item in slices for arch in item["SupportedArchitectures"]}
            if not required.issubset(found):
                raise ValueError(f"Missing {name} slices in {component}: {required - found}")
            if component == "ffmpegkit":
                for item in slices:
                    inner = framework / item["LibraryIdentifier"] / item["LibraryPath"]
                    plists = list(inner.rglob("Info.plist"))
                    if not plists or any(plistlib.loads(p.read_bytes()).get("CFBundleShortVersionString") != version for p in plists):
                        raise ValueError(f"Wrong {name} wrapper version")


def smoke_windows():
    ct.windll.kernel32.SetErrorMode(2)
    base = REPO / CONFIG["platforms"]["windows"]["binary_path"] / "bin"
    with os.add_dll_directory(str(base)):
        lib = ct.CDLL(str(next(base.glob("libffmpegkit-*.dll"))))
    signatures = {
        "ffk_string_free": (None, [ct.c_void_p]),
        "ffk_config_get_ffmpeg_version": (ct.c_void_p, []),
        "ffk_config_get_version": (ct.c_void_p, []),
        "ffk_ffmpegkit_execute_with_arguments": (ct.c_void_p, [ct.POINTER(ct.c_char_p), ct.c_size_t]),
        "ffk_session_get_return_code": (ct.c_int, [ct.c_void_p, ct.POINTER(ct.c_int)]),
        "ffk_session_get_output": (ct.c_void_p, [ct.c_void_p]),
        "ffk_session_free": (None, [ct.c_void_p]),
        "ffk_config_register_ffmpegkit_input_buffer": (ct.c_long, [ct.POINTER(ct.c_uint8), ct.c_size_t]),
        "ffk_config_register_ffmpegkit_output_buffer": (ct.c_long, [ct.c_long, ct.c_long]),
        "ffk_config_get_ffmpegkit_output_buffer": (ct.c_int, [ct.c_long, ct.POINTER(ct.POINTER(ct.c_uint8)), ct.POINTER(ct.c_size_t)]),
        "ffk_config_unregister_ffmpegkit_buffer": (None, [ct.c_long]),
        "ffk_bytes_free": (None, [ct.c_void_p]),
    }
    for name, (returns, args) in signatures.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = returns, args

    def string(ptr):
        try:
            return ct.string_at(ptr).decode("utf-8", errors="replace") if ptr else ""
        finally:
            lib.ffk_string_free(ptr)

    ffmpeg_version = string(lib.ffk_config_get_ffmpeg_version())
    wrapper_version = string(lib.ffk_config_get_version())
    if "9.0.2" not in ffmpeg_version or wrapper_version != CONFIG["wrapper_version"]:
        raise ValueError(f"Wrong runtime versions: FFmpeg {ffmpeg_version}, wrapper {wrapper_version}")

    def execute(args):
        encoded = [a.encode("utf-8") for a in args]
        argv = (ct.c_char_p * len(encoded))(*encoded)
        session = lib.ffk_ffmpegkit_execute_with_arguments(argv, len(encoded))
        if not session:
            raise ValueError("Native session creation failed")
        try:
            code = ct.c_int()
            present = lib.ffk_session_get_return_code(session, ct.byref(code))
            output = string(lib.ffk_session_get_output(session))
            if not present or code.value != 0:
                raise ValueError(f"FFmpeg failed ({code.value}): {output}")
            return output
        finally:
            lib.ffk_session_free(session)

    encoders = execute(["-encoders"])
    for encoder in ["libx264", "libx265", "libmp3lame"]:
        if encoder not in encoders:
            raise ValueError(f"Missing encoder {encoder}")
    if "libdav1d" not in execute(["-decoders"]) or "zscale" not in execute(["-filters"]):
        raise ValueError("Missing dav1d/zimg")
    protocols = execute(["-protocols"])
    if not all(p in protocols for p in ["ffkitmem", "ffkitstream"]):
        raise ValueError("Missing buffer/stream protocols")
    with tempfile.TemporaryDirectory() as folder:
        execute(["-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=2", "-frames:v", "2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(Path(folder) / "test.mp4")])
    for blur_filter in ("gblur=sigma=10:steps=3", "dblur", "bilateral=planes=7"):
        for pixel_format in ("yuv420p", "yuv420p10le"):
            for width in (572, 574):
                execute(["-hide_banner", "-nostats", "-loglevel", "error",
                         "-f", "lavfi", "-i", f"testsrc2=size={width}x140:rate=30",
                         "-filter_threads", "2", "-vf", f"format={pixel_format},{blur_filter}",
                         "-frames:v", "90", "-f", "null", "-"])
    raw = bytes([64, 128, 192, 255]) * 4
    data = (ct.c_uint8 * len(raw)).from_buffer_copy(raw)
    source = lib.ffk_config_register_ffmpegkit_input_buffer(data, len(raw))
    target = lib.ffk_config_register_ffmpegkit_output_buffer(1024, 4096)
    try:
        execute(["-y", "-f", "rawvideo", "-pixel_format", "rgba", "-video_size", "2x2", "-i", f"ffkitmem:{source}",
                 "-frames:v", "1", "-c:v", "rawvideo", "-pix_fmt", "rgba", "-f", "rawvideo", f"ffkitmem:{target}"])
        output, length = ct.POINTER(ct.c_uint8)(), ct.c_size_t()
        if not lib.ffk_config_get_ffmpegkit_output_buffer(target, ct.byref(output), ct.byref(length)):
            raise ValueError("Native memory output missing")
        try:
            if ct.string_at(output, length.value) != raw:
                raise ValueError("Native memory roundtrip changed pixels")
        finally:
            lib.ffk_bytes_free(output)
    finally:
        lib.ffk_config_unregister_ffmpegkit_buffer(source)
        lib.ffk_config_unregister_ffmpegkit_buffer(target)
    print(f"Windows smoke passed: FFmpeg {ffmpeg_version}, Studio encoders, native memory roundtrip")


def bash_run(args, shell):
    if sys.platform == "win32":
        if not shell:
            shell = str(REPO / ".toolchain/msys64/usr/bin/bash.exe")
        env = dict(os.environ, MSYSTEM="CLANG64", CHERE_INVOKING="1")
        converted = run([shell, "-c", '/usr/bin/cygpath -u "$1"', "studio", str(REPO)], capture=True, env=env).strip()
        command = "cd " + shlex.quote(converted) + " && " + shlex.join(args)
        run([shell, "-lc", command], env=env)
    else:
        run([shell or "bash", *args])


def receipt_path(name):
    return DIST / f"{name}.json"


def verify_receipt(root, receipt, name):
    if receipt.get("identity") != identity() or receipt.get("platform") != name:
        raise ValueError(f"{name}: different source/profile; rebuild from this preparation")
    expected = files_manifest(root, CONFIG["platforms"][name]["binary_path"])
    if expected != receipt.get("files"):
        raise ValueError(f"{name}: binaries changed or incomplete; rebuild/re-import")
    check_binaries(root, name)


def build(name, shell, resume=False):
    check_source()
    prepare_source()
    if name == "windows" and sys.platform != "win32":
        raise ValueError("Build Windows on an x64 Windows host")
    if name in ("ios", "macos") and sys.platform != "darwin":
        raise ValueError("Apple builds require a Mac with Xcode 26 and Nix")
    entry = CONFIG["platforms"][name]
    DIST.mkdir(parents=True, exist_ok=True)
    receipt_path(name).unlink(missing_ok=True)
    extra = ["--no-workspace-cleanup-ffmpeg"] if resume and name == "windows" else []
    bash_run(["./" + entry["script"], *CONFIG["common_args"], *entry["args"], *extra], shell)
    actual_ffmpeg = run(["git", "-C", "src/ffmpeg", "rev-parse", "HEAD"], capture=True).strip()
    expected_ffmpeg = run(["git", "-C", "src/ffmpeg", "rev-parse", CONFIG["ffmpeg_source"] + "^{commit}"], capture=True).strip()
    pinned_ffmpeg = run(["git", "-C", "src/ffmpeg", "rev-parse", CONFIG["ffmpeg_commit"] + "^{commit}"], capture=True).strip()
    if actual_ffmpeg != expected_ffmpeg or actual_ffmpeg != pinned_ffmpeg:
        raise ValueError("Build used a different FFmpeg source commit")
    bash_run(["flutter/flutter/copy_local_binaries.sh", name], shell)
    check_binaries(REPO, name)
    if name == "windows":
        smoke_windows()
    receipt = {"identity": identity(), "platform": name, "host": platform.platform(),
               "ffmpeg_checkout": actual_ffmpeg,
               "files": files_manifest(REPO, entry["binary_path"])}
    receipt_path(name).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    export(name)


def export(name):
    receipt = json.loads(receipt_path(name).read_text(encoding="utf-8"))
    verify_receipt(REPO, receipt, name)
    archive = DIST / f"{CONFIG['tag']}-{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        binary_path = CONFIG["platforms"][name]["binary_path"]
        bundle.add(REPO / binary_path, arcname=binary_path)
        bundle.add(receipt_path(name), arcname=f"studio-manifest-{name}.json")
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest(archive)}  {archive.name}\n", encoding="utf-8")
    print(f"READY: {archive}")


def import_archive(archive):
    archive = Path(archive).resolve()
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    if digest(archive) != checksum.read_text().split()[0]:
        raise ValueError("Archive checksum does not match")
    with tempfile.TemporaryDirectory() as folder:
        staging = Path(folder)
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            manifests = [n for n in names if n.startswith("studio-manifest-") and "/" not in n]
            if len(manifests) != 1:
                raise ValueError("Expected exactly one platform manifest")
            member = bundle.extractfile(manifests[0])
            receipt = json.load(member)
            name = receipt["platform"]
            if name not in CONFIG["platforms"]:
                raise ValueError("Unknown platform")
            prefix = CONFIG["platforms"][name]["binary_path"]
            for item in bundle.getmembers():
                normalized = PurePosixPath(item.name)
                if normalized.is_absolute() or ".." in normalized.parts or "\\" in item.name:
                    raise ValueError("Unsafe archive path")
                if item.name != manifests[0] and item.name != prefix and not item.name.startswith(prefix + "/"):
                    raise ValueError("Unexpected archive member")
            bundle.extractall(staging, filter="data")
        verify_receipt(staging, receipt, name)
        destination = REPO / prefix
        if destination.exists():
            raise ValueError(f"Destination already exists; use a fresh assembly checkout: {destination}")
        import shutil
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging / prefix, destination, symlinks=True)
        DIST.mkdir(parents=True, exist_ok=True)
        receipt_path(name).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    export(name)


def release(publish, tag_local=False):
    notes = DIST / "RELEASE-NOTES.md"
    if publish and not notes.is_file():
        raise ValueError(f"Missing local release notes: {notes}")
    check_source()
    binaries = []
    assets = []
    for name, entry in CONFIG["platforms"].items():
        receipt = json.loads(receipt_path(name).read_text(encoding="utf-8"))
        verify_receipt(REPO, receipt, name)
        for relative, details in receipt["files"].items():
            if details.get("size", 0) >= 100 * 1024 * 1024:
                raise ValueError(f"GitHub git file limit exceeded: {relative}")
        binaries.append(entry["binary_path"])
        export(name)
        assets += [DIST / f"{CONFIG['tag']}-{name}.tar.gz", DIST / f"{CONFIG['tag']}-{name}.tar.gz.sha256"]
    print(f"All four platforms verified. Single tag: {CONFIG['tag']}")
    prepare_source()
    if not publish and not tag_local:
        print("Review the artifacts, then run: ./profiles/release.sh studio --skip-build")
        return
    remote = run(["git", "remote", "get-url", "origin"], capture=True).strip()
    if CONFIG["repository"] not in remote:
        raise ValueError("origin is not the requested fork")
    tag = CONFIG["tag"]
    if run(["git", "tag", "--list", tag], capture=True).strip():
        raise ValueError("Tag already exists; never overwrite a published tag")
    if publish and run(["git", "ls-remote", "--tags", "origin", "refs/tags/" + tag], capture=True).strip():
        raise ValueError("Tag already exists on origin; never overwrite a published tag")
    run(["git", "var", "GIT_AUTHOR_IDENT"], capture=True)
    run(["git", "diff", "--quiet", "HEAD", "--", "profiles"])
    with tempfile.TemporaryDirectory() as folder:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(folder) / "index"))
        run(["git", "read-tree", "HEAD"], env=env)
        run(["git", "add", "-f", "--", *binaries], env=env)
        tree = run(["git", "write-tree"], capture=True, env=env).strip()
        commit = run(["git", "commit-tree", tree, "-p", "HEAD", "-m", f"release: {tag} (FFmpeg 9.0.2, Studio, four platforms)"], capture=True).strip()
    flags = "\n".join(name + ": " + shlex.join([*CONFIG["common_args"], *entry["args"]])
                      for name, entry in CONFIG["platforms"].items())
    run(["git", "tag", "-a", tag, commit, "-m", f"{tag}\n\nFFmpeg {CONFIG['ffmpeg_source']}; source {CONFIG['base_commit']}\n\n{flags}"])
    if not publish:
        print(f"Tagged locally: {tag} ({commit}). No push or GitHub release performed.")
        return
    run(["git", "push", "origin", "refs/tags/" + tag])
    run(["gh", "release", "create", tag, "--repo", CONFIG["repository"], "--verify-tag", "--draft", "--title", tag, "--notes-file", notes, *assets])
    print("Draft release created. Verify the git dependency and Flutter apps before publishing it:")
    print(f"gh release edit {tag} --repo {CONFIG['repository']} --draft=false")


def main():
    parser = argparse.ArgumentParser(description="Build and release the Studio profile with native Flutter binaries")
    parser.add_argument("command", choices=["plan", "build", "export", "import", "verify", "release"])
    parser.add_argument("targets", nargs="*")
    parser.add_argument("--bash", help="Path to MSYS2 bash.exe on Windows")
    parser.add_argument("--resume", action="store_true", help="Reuse FFmpeg object files after a Windows build interruption; use only with unchanged source/profile")
    parser.add_argument("--publish", action="store_true", help="Create/push one tag and create one draft GitHub release")
    parser.add_argument("--tag", action="store_true", help="Create the binary-bearing release commit and tag locally")
    args = parser.parse_args()
    if args.command == "plan":
        print(json.dumps(CONFIG, indent=2))
    elif args.command == "release":
        release(args.publish, args.tag)
    elif args.command == "import":
        for archive in args.targets:
            import_archive(archive)
    else:
        if not args.targets:
            parser.error("Specify at least one platform")
        for name in args.targets:
            if name not in CONFIG["platforms"]:
                parser.error(f"Unknown platform: {name}")
            if args.command == "build":
                build(name, args.bash, args.resume)
            elif args.command == "export":
                export(name)
            else:
                verify_receipt(REPO, json.loads(receipt_path(name).read_text()), name)
                print(f"Verified: {name}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError, KeyError) as error:
        sys.exit(f"error: {error}")
