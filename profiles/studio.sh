platforms=(android ios macos)

android_args=(
  -p android-r27d --speed --api-level=24
  --disable-arm-v7a --disable-x86
  --enable-gpl
  --enable-x264 --enable-x265 --enable-zimg --enable-lame --enable-dav1d
  --enable-android-zlib --enable-android-media-codec
)

ios_args=(
  -p xcode26 -x --speed --target=15.0
  --disable-armv7 --disable-armv7s --disable-arm64e --disable-i386
  --disable-arm64-mac-catalyst --disable-x86-64-mac-catalyst
  --enable-gpl
  --enable-x264 --enable-x265 --enable-zimg --enable-lame --enable-dav1d
  --enable-ios-zlib --enable-ios-bzip2 --enable-ios-libiconv --enable-ios-videotoolbox
)

macos_args=(
  -p xcode26 -x --speed --target=10.15
  --enable-gpl
  --enable-x264 --enable-x265 --enable-zimg --enable-lame --enable-dav1d
  --enable-macos-zlib --enable-macos-bzip2 --enable-macos-libiconv --enable-macos-videotoolbox
)
