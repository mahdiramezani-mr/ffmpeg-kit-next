#!/usr/bin/env bash

set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${1:?usage: tools/apply-ffmpeg-patches.sh <ffmpeg-source-directory>}"
source_dir="$(cd "${source_dir}" && pwd)"
source_file="${source_dir}/libavcodec/h2645_vui.c"
patch_file="${repo_dir}/tools/patch/make/ffmpeg/c80002aa-h2645-reserved-color.patch"
upstream_commit="c80002aa81e39f6bcc8d08c13acf8f9f61105cb0"
base_commit="3a0867c2bfda4a4d4309ca1a8cbdc6175e67f587"
original_blob="e5c7bf46f9b3d18f061f33b8ac29f16eb41933c2"
patched_blob="0e576c15632a39013103e9e3bd093568a4423bcb"

if [[ "$(git -C "${source_dir}" rev-parse HEAD)" != "${base_commit}" ]]; then
  echo "error: FFmpeg source is not the pinned n7.1.5 commit ${base_commit}" >&2
  exit 1
fi

case "$(git hash-object "${source_file}")" in
  "${original_blob}")
    git -C "${source_dir}" apply --check "${patch_file}"
    git -C "${source_dir}" apply "${patch_file}"
    echo "Applied official FFmpeg patch ${upstream_commit}"
    ;;
  "${patched_blob}")
    echo "Official FFmpeg patch ${upstream_commit} is already applied"
    ;;
  *)
    echo "error: unexpected h2645_vui.c content; refusing to apply ${upstream_commit}" >&2
    exit 1
    ;;
esac

[[ "$(git hash-object "${source_file}")" == "${patched_blob}" ]]
