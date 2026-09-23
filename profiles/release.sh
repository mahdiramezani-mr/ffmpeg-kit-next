#!/usr/bin/env bash

set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_dir="${repo_dir}/flutter/flutter"

usage() {
  cat <<EOF
Usage: profiles/release.sh <profile> [--skip-build] [--push]

Builds the native binaries of profiles/<profile>.sh, copies them into the Flutter
plugin, commits them on top of the current branch without moving it and tags
that commit v<version>-<profile>.<n>. The branch never receives the binaries.

  --skip-build   reuse what is already in prebuilt/ instead of running nix
  --push         push the new tag to origin
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

binary_dir() {
  case "$1" in
    android) echo "android/libs-maven" ;;
    ios) echo "ios/ffmpeg_kit_next_flutter/Frameworks" ;;
    macos) echo "macos/ffmpeg_kit_next_flutter/Frameworks" ;;
    linux) echo "linux/Frameworks" ;;
    *) die "unknown platform '$1'" ;;
  esac
}

apple_binary_version() {
  local plist
  plist="$(find "${plugin_dir}/$(binary_dir "$1")/ffmpegkit.xcframework" -path '*ffmpegkit.framework*' -name Info.plist | head -1)"
  [[ -n "${plist}" ]] || die "$1: no ffmpegkit.framework Info.plist found"
  /usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${plist}"
}

assert_binary_version() {
  local platform="$1" found
  case "${platform}" in
    android)
      [[ -d "${plugin_dir}/android/libs-maven/com/arthenica/ffmpeg-kit-next/${version}" ]] ||
        die "android: prebuilt AAR is not version ${version}; rebuild without --skip-build"
      ;;
    ios | macos)
      found="$(apple_binary_version "${platform}")"
      [[ "${found}" == "${version}" ]] ||
        die "${platform}: prebuilt frameworks are version ${found}, not ${version}; rebuild without --skip-build"
      ;;
  esac
}

tag_exists() {
  git rev-parse -q --verify "refs/tags/$1" >/dev/null ||
    [[ -n "$(git ls-remote --tags origin "refs/tags/$1")" ]]
}

profile=""
skip_build=0
push=0
while (($# > 0)); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --skip-build) skip_build=1 ;;
    --push) push=1 ;;
    -*) usage >&2; die "unknown option '$1'" ;;
    *) [[ -z "${profile}" ]] || die "only one profile can be released at a time"; profile="$1" ;;
  esac
  shift
done
[[ -n "${profile}" ]] || { usage >&2; exit 1; }

profile_file="${repo_dir}/profiles/${profile}.sh"
[[ -f "${profile_file}" ]] || die "no profile file: profiles/${profile}.sh"
source "${profile_file}"

cd "${repo_dir}"
[[ -z "$(git status --porcelain)" ]] || die "working tree is not clean"
source_branch="$(git symbolic-ref -q --short HEAD)" || die "check out a profiles branch first"
version="$(sed -n 's/^version: *//p' "${plugin_dir}/pubspec.yaml")"

n=1
while tag_exists "v${version}-${profile}.${n}"; do
  n=$((n + 1))
done
tag="v${version}-${profile}.${n}"
echo "releasing ${tag} from ${source_branch}"

if ((skip_build == 0)); then
  for platform in "${platforms[@]}"; do
    args_ref="${platform}_args[@]"
    "./nix-${platform}.sh" "${!args_ref}"
  done
fi

(cd "${plugin_dir}" && ./copy_local_binaries.sh "${platforms[@]}")

binary_paths=()
flags_summary=""
for platform in "${platforms[@]}"; do
  assert_binary_version "${platform}"
  binary_paths+=("flutter/flutter/$(binary_dir "${platform}")")
  args_ref="${platform}_args[@]"
  flags_summary+="${platform}: ${!args_ref}"$'\n'
done

release_index="$(mktemp)"
trap 'rm -f "${release_index}"' EXIT
GIT_INDEX_FILE="${release_index}" git read-tree HEAD
GIT_INDEX_FILE="${release_index}" git add -f -- "${binary_paths[@]}"
release_tree="$(GIT_INDEX_FILE="${release_index}" git write-tree)"
release_commit="$(git commit-tree "${release_tree}" -p HEAD \
  -m "release: ${tag}" \
  -m "Native binaries of the ${profile} profile, built from ${source_branch}." \
  -m "${flags_summary}")"
git tag -a "${tag}" "${release_commit}" -m "${tag}" -m "${flags_summary}"

echo "tagged ${tag} ($(git rev-parse --short "${release_commit}"))"
if ((push == 1)); then
  git push origin "${tag}"
else
  echo "push it with: git push origin ${tag}"
fi
