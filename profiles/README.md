# Prebuilt profiles

This fork publishes the Flutter plugin (`flutter/flutter`) **with its native
binaries committed**, so an app consumes it straight from git without building
FFmpeg. Each build configuration is a named profile.

## Automated releases

Use [Publish Studio](PUBLISHING.md) to build Android, iOS, macOS and Windows
on GitHub Actions from an upstream tag. It preserves the binary-bearing Git
dependency and applies the remaining local patches. The scripts below remain
available for historical Studio releases.

## Using a release

```yaml
dependencies:
  ffmpeg_kit_next_flutter:
    git:
      url: https://github.com/mahdiramezani-mr/ffmpeg-kit-next.git
      path: flutter/flutter
      ref: v9.0.2-studio.1
```

Always reference a tag, never a branch: branches carry no binaries.

On Android the app must also register the plugin's bundled Maven repository in
its project-level `android/build.gradle` (see `flutter/flutter/BUILD.md`):

```groovy
allprojects {
    repositories {
        def ffmpegKitProject = rootProject.findProject(":ffmpeg_kit_next_flutter")
        if (ffmpegKitProject != null) {
            maven { url "${ffmpegKitProject.projectDir}/libs-maven" }
        }
    }
}
```

## Tags

`v<plugin version>-<profile>.<n>`

- **plugin version**: the upstream release the build is based on (`9.0.2` uses FFmpeg n9.0.2).
- **profile**: which library set, from the table below.
- **n**: the build number. A rebuild of the same version and profile (new
  flags, toolchain, security fix in a library) gets the next number; a published
  tag is never moved.

The tag message lists the exact native flags each platform was built with.

## Profiles

| Profile | For | Libraries | License |
|---------|-----|-----------|---------|
| `studio` | video editing and export | x264, x265, dav1d, lame, zimg, zlib, libiconv; bzip2 + VideoToolbox on Apple, MediaCodec on Android | GPL |

Platforms of `studio`: Android `arm64-v8a` `armeabi-v7a` `x86_64` (API 24),
iOS `arm64` + simulator `arm64` `x86_64` (15.0), macOS universal (10.15), and Windows x64.

## Branches

| Branch | Contents |
|--------|----------|
| `main` | upstream source and the Studio workflow entry point; default branch |
| `profiles` | Studio release tooling, configuration, patches and historical build scripts |
| `profiles-7.1` | upstream `v7.1.0` + the same, with 7.1 flag names |

Profile flags are written per branch because upstream renamed its build
options in 8.x (`--enable-x264` became `--enable-lib-x264`). A separate
branch for every FFmpeg version is unnecessary.

## Releasing

Use [Publish Studio](PUBLISHING.md) for current releases. It builds from a
selected upstream tag, applies the configured patches and publishes a Git tag
containing the native binaries. Local platform builds are not required.

### Historical build scripts

The commands below describe the earlier release process and remain available
for maintaining historical versions.

```bash
git switch profiles                          # or profiles-7.1
./profiles/release.sh studio                 # nix build, copy, commit, tag
./profiles/release.sh studio --skip-build    # reuse prebuilt/
git push origin v<version>-studio.<n>        # or pass --push
```

The binaries are committed on a commit that sits only behind its tag, so the
branches stay small and merge cleanly with upstream. Every release still adds
native binary data that each consumer downloads when resolving the Git dependency.

For Studio 9, `studio.json` pins the source and patch series. `studio.py`
verifies matching receipts for Windows, Android, iOS and macOS before tagging.
Build Windows on Windows and the other three platforms on a Mac.

```bash
python3 profiles/studio.py build android ios macos
python3 profiles/studio.py import /path/to/v9.0.0-studio.1-windows.tar.gz
python3 profiles/studio.py verify windows android ios macos
```

Studio's `--push` option also creates a draft GitHub release and reads its
notes from the untracked `prebuilt/studio-release/RELEASE-NOTES.md`.
Use it only when creating a new tag. Existing tags must not be overwritten.

## Updating from upstream

For automated releases, select a new upstream tag in Publish Studio and review
patch compatibility. The workflow checks out that source independently of the
`profiles` branch.

Keep `main` synchronized with upstream using normal merges while retaining its
publishing workflow. Published tags must not be moved or overwritten.

## Adding a profile

Create `profiles/<name>.sh` with `platforms=(...)` and one `<platform>_args=(...)`
array per platform, add it to the table above, and release it.
