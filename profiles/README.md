# Prebuilt profiles

This fork publishes the Flutter plugin (`flutter/flutter`) **with its native
binaries committed**, so an app consumes it straight from git without building
FFmpeg. Each build configuration is a named profile.

## Using a release

```yaml
dependencies:
  ffmpeg_kit_next_flutter:
    git:
      url: https://github.com/mahdiramezani-mr/ffmpeg-kit-next.git
      path: flutter/flutter
      ref: v7.1.0-studio.1
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

- **plugin version**: the upstream release the build is based on (`7.1.0` is FFmpeg 7.1).
- **profile**: which library set, from the table below.
- **n**: the build number. A rebuild of the same version and profile (new
  flags, toolchain, security fix in a library) gets the next number; a published
  tag is never moved.

The tag message lists the exact nix flags each platform was built with.

## Profiles

| Profile | For | Libraries | License |
|---------|-----|-----------|---------|
| `studio` | video editing and export | x264, x265, dav1d, lame, zimg, zlib, libiconv; bzip2 + VideoToolbox on Apple, MediaCodec on Android | GPL |
| `gif` | raw RGBA stream to transparent GIF | rawvideo decoder, GIF encoder, file/ffkitstream protocols, palette filters | LGPL |

Platforms of `studio` and `gif`: Android `arm64-v8a` `armeabi-v7a` `x86_64` (API 24),
iOS `arm64` + simulator `arm64` `x86_64` (15.0), macOS universal (10.15).

## Branches

| Branch | Contents |
|--------|----------|
| `main` | upstream `main`, untouched; update it with GitHub's *Sync fork* |
| `profiles` | upstream `main` + this directory + fixes not yet upstream |
| `profiles-7.1` | upstream `v7.1.0` + the same, with 7.1 flag names |

Profile flags are written per branch because upstream renamed its build
options in 8.x (`--enable-x264` became `--enable-lib-x264`).

## Releasing

```bash
git switch profiles                          # or profiles-7.1
./profiles/release.sh studio                 # nix build, copy, commit, tag
./profiles/release.sh studio --skip-build    # reuse prebuilt/
git push origin v<version>-studio.<n>        # or pass --push
```

The binaries are committed on a commit that sits only behind its tag, so the
branches stay small and merge cleanly with upstream. Every release still adds
~200 MB that each consumer's `pub get` downloads once; delete tags nobody uses.

## Updating from upstream

```bash
git fetch upstream
git switch main && git merge --ff-only upstream/main && git push origin main
git switch profiles && git merge main
```

Then check that `profiles/*.sh` still matches the flags in
`./nix-<platform>.sh --help` before the next release.

## Adding a profile

Create `profiles/<name>.sh` with `platforms=(...)` and one `<platform>_args=(...)`
array per platform, add it to the table above, and release it.

Profiles can export `FFMPEG_KIT_EXTRA_CONFIGURE_FLAGS` to select native FFmpeg
components. The release tag records these flags alongside the platform flags.
