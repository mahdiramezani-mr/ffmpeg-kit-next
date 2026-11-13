#!/usr/bin/env bash
set -euo pipefail

[[ "${MSYSTEM}" == CLANG64 ]]
version=22.1.8
prefix=mingw-w64-clang-x86_64
packages=(clang:2 clang-libs:2 compiler-rt:2 lld:2 llvm:2 llvm-libs:2 llvm-tools:2 libc++:1 libunwind:1)
for name in clang-analyzer clang-tools-extra gcc-compat; do
  if pacman -Q "${prefix}-${name}" >/dev/null 2>&1; then
    packages+=("${name}:2")
  fi
done
urls=()
for spec in "${packages[@]}"; do
  urls+=("https://repo.msys2.org/mingw/clang64/${prefix}-${spec%:*}-${version}-${spec##*:}-any.pkg.tar.zst")
done
pacman --noconfirm -U "${urls[@]}"
for spec in "${packages[@]}"; do
  [[ "$(pacman -Q "${prefix}-${spec%:*}")" == "${prefix}-${spec%:*} ${version}-${spec##*:}" ]]
done
clang --version
ld.lld --version
cmake --version
meson --version
ninja --version
