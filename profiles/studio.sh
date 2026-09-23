platforms=(android ios macos)

android_args=(
  -p android-r27d --speed --api-level=24
  --disable-arch-arm-v7a --disable-arch-x86
  --enable-gpl
  --enable-lib-x264 --enable-lib-x265 --enable-lib-zimg --enable-lib-lame --enable-lib-dav1d
  --enable-lib-android-zlib --enable-lib-android-media-codec
)

ios_args=(
  -p xcode26 -x --speed --target=15.0
  --disable-arch-arm64e --disable-arch-arm64-mac-catalyst --disable-arch-x86-64-mac-catalyst
  --enable-gpl
  --enable-lib-x264 --enable-lib-x265 --enable-lib-zimg --enable-lib-lame --enable-lib-dav1d
  --enable-lib-ios-zlib --enable-lib-ios-bzip2 --enable-lib-ios-libiconv --enable-lib-ios-videotoolbox
)

macos_args=(
  -p xcode26 -x --speed --target=10.15
  --enable-gpl
  --enable-lib-x264 --enable-lib-x265 --enable-lib-zimg --enable-lib-lame --enable-lib-dav1d
  --enable-lib-macos-zlib --enable-lib-macos-bzip2 --enable-lib-macos-libiconv --enable-lib-macos-videotoolbox
)
