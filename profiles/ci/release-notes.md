Native FFmpegKitNext {{WRAPPER_VERSION}} binaries for video editing and export, based on FFmpeg {{FFMPEG_VERSION}}, with the Studio library profile.

## Changes

- Restore 10-bit x265 encoding on Android, iOS, macOS and Windows. Software HEVC exports now support Main 10 instead of silently falling back to 8-bit output.
- Verify an encoded HEVC file with FFprobe during the Windows and macOS native checks, requiring Main 10 and `yuv420p10le` output.

See the [upstream release notes](https://github.com/arthenica/ffmpeg-kit-next/releases/tag/{{UPSTREAM_TAG}}) for changes included in {{UPSTREAM_TAG}}.

## Retained Studio patches

- Prevent Windows x64 crashes in the `gblur`, `dblur` and `bilateral` filters with Clang 22, preserving the filtering algorithms.
- Handle default Flutter buffer and stream options on iOS and macOS by normalizing `NSNull` arguments.
- Work around the Clang 22 compiler crash in `colorspacedsp.c` on Windows.

## Capabilities

Included libraries: x264, x265, dav1d, LAME, zimg and zlib. Apple builds also enable libiconv, bzip2 and VideoToolbox; Android enables MediaCodec. All platforms use `--speed` and enable GPL components.

The x265 build produces 10-bit HEVC output. It accepts 8-bit input, but does not include a separate 8-bit x265 encoder; use x264 for 8-bit software H.264 output.

## Supported platforms

- Android API 24: armeabi-v7a (NEON), arm64-v8a and x86_64; NDK r27d.
- iOS 15.0: arm64 devices and arm64/x86_64 simulators.
- macOS 10.15: universal arm64/x86_64.
- Windows x64: bundled native libraries built with MSYS2 CLANG64; Flutter applications built with Visual Studio.

## Installation

Add the following dependency to your app's `pubspec.yaml`:

```yaml
dependencies:
  ffmpeg_kit_next_flutter:
    git:
      url: https://github.com/mahdiramezani-mr/ffmpeg-kit-next.git
      path: flutter/flutter
      ref: {{RELEASE_TAG}}
```

Native binaries are included at this tag. Android apps must register the plugin's bundled Maven repository in their project-level `android/build.gradle`:

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

iOS and macOS use the bundled frameworks through CocoaPods or Swift Package Manager. On Windows, the plugin bundles its native DLLs with the Flutter application; distribute the complete application output together with the native bundle licenses.

## Validation

- Windows x64 and macOS arm64 native runtime checks covered loading, versions, Studio encoders, blur filters, video export and cancellation of a running session.
- Main 10 regression checks encoded a 10-bit input through libx265 and verified the final HEVC profile and pixel format with FFprobe. Automatic conversion to an 8-bit encoder input is disabled for this check.
- Blur regression checks covered `gblur`, `dblur` and `bilateral` with 8-bit and 10-bit pixel formats at widths 572 and 574.
- Android and iOS packages were checked for the supported architectures and wrapper version. This workflow does not run Android/iOS applications or Flutter integration tests.
- The release step verified that all four bundles came from the same source and patch set, and checked their file hashes before assembly.

## License

This profile enables GPL components. The annotated tag records the exact platform build flags. Source commits, patch identity and native file hashes are recorded in `release-build.json`; build settings are available in `profiles/publish.json`.
