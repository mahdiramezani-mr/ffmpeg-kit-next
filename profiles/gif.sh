ffmpeg_configure_args=(
  --disable-everything
  --disable-autodetect
  --disable-network
  --enable-zlib
  --enable-demuxer=image2
  --enable-parser=png
  --enable-decoder=png
  --enable-encoder=gif
  --enable-muxer=gif
  --enable-protocol=file
  --enable-filter=split,palettegen,paletteuse,format,scale,null,trim
  --enable-swscale
)

export FFMPEG_KIT_EXTRA_CONFIGURE_FLAGS="${ffmpeg_configure_args[*]}"

platforms=(android ios macos)

android_args=(
  -p android-r27d --speed --api-level=24
  --disable-arm-v7a --disable-x86
  --enable-android-zlib
  --rebuild-ffmpeg
)

ios_args=(
  -p xcode26 -x --speed --target=15.0
  --disable-armv7 --disable-armv7s --disable-arm64e --disable-i386
  --disable-arm64-mac-catalyst --disable-x86-64-mac-catalyst
  --enable-ios-zlib
  --rebuild-ffmpeg
)

macos_args=(
  -p xcode26 -x --speed --target=10.15
  --enable-macos-zlib
  --rebuild-ffmpeg
)
