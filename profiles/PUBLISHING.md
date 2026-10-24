# Studio release publishing

The Publish Studio workflow builds Android, iOS, macOS and Windows x64 in parallel on GitHub Actions. The default branch remains `main`. Release tooling, configuration and patches are maintained on `profiles`.

## Publish a release

1. Open [Actions > Publish Studio](https://github.com/mahdiramezani-mr/ffmpeg-kit-next/actions/workflows/publish-studio.yml) and select **Run workflow**.
2. Keep the branch set to `main` and enter an upstream tag, such as `v9.0.2`.
3. Keep `build_number=0` to select the next available Studio build number automatically. For example, the first build produces `v9.0.2-studio.1`.
4. Select `draft` to review the release before publication, or `publish` to publish automatically after every build and verification step succeeds.
5. Start the workflow. It builds all four platforms, assembles the binary-bearing Git tag and uploads the release assets.
6. For a draft, review the output in **Releases** and select **Publish release**. Publishing the draft does not rebuild the binaries.

Both `draft` and `publish` push the Git tag. `build-only` stores the output as CI artifacts without creating a remote tag or release; publishing through the workflow interface afterward requires a new run. An explicit positive build number can also be provided. Published tags are immutable.

## Maintain patches and build settings

1. Check out `profiles`.
2. Add patches under `profiles/ci/patches/` and register them in `profiles/publish.json`.
3. Update platform flags, architectures and toolchain settings in the same configuration as required. LLVM package versions must also match `profiles/ci/setup-windows.sh`.
4. Commit and push the changes to `profiles`, then start Publish Studio from `main`.
5. If upstream already contains an exact patch, the workflow skips applying it again. A conflicting patch stops the build and must be reviewed or rebased for the selected upstream tag.

Release descriptions use `profiles/ci/release-notes.md`. Versions, tags and source links are substituted automatically. Update the template when capabilities, architectures or validation coverage change.

Keep `Changes` limited to differences from the preceding Studio release. List patches still applied on top of upstream under `Retained Studio patches`, and link to upstream release notes for inherited changes.

Each release starts from the selected upstream tag and adds the configured patches and native bundles. Native changes and binaries do not need to be merged into `main`.

The workflow on `main` delegates to the reusable workflow on `profiles`. Its reference definition is `profiles/ci/dispatch.yml`. Update both definitions when changing the dispatch interface. Patch and build-flag changes require updates only on `profiles`.

## Retry failed runs

- Use **Re-run failed jobs** for transient failures. CI artifacts are retained for 14 days.
- Each run pins the tooling and source commits. Tooling or patch changes require a new run.
- If the tag was pushed but release creation failed, retrying proceeds only when the assembled content matches the existing tag.
- For a new run after a tag already exists, use build number `0` to select the next available number.
- Hosted jobs have a six-hour limit. Builds exceeding this limit must be split by architecture before publication.
- Windows currently uses LLVM `22.1.8`; Xcode is pinned to `26.6`. Toolchain updates require compatibility and regression checks.

## Outputs and validation

- Native binaries are committed at the release tag. Flutter applications use the package at `flutter/flutter`.
- Each release also includes four `.tar.gz` native bundles and their SHA-256 checksums. These downloads are optional for applications using the Git dependency.
- `release-build.json` records the upstream and FFmpeg commits, tooling and patch identity, build flags and native file hashes.
- Windows and macOS run native checks for versions, enabled libraries, blur filters, video export and cancellation.
- Android and iOS packages are checked for architecture and version coverage. Device runtime and Flutter integration tests are outside this workflow's coverage.
- The current profile does not build Linux, Web, tvOS, visionOS or Windows arm64.
- The workflow uses `GITHUB_TOKEN`; no additional PAT or secret is required. Only the release job receives write access.

## Consume a release

```yaml
dependencies:
  ffmpeg_kit_next_flutter:
    git:
      url: https://github.com/mahdiramezani-mr/ffmpeg-kit-next.git
      path: flutter/flutter
      ref: v9.0.2-studio.1
```

Follow `flutter/flutter/BUILD.md` for Android Maven registration and Apple/Windows integration. The publishing workflow pushes only its selected release tag; a bulk tag push or force-push is not required.

## Check release tooling locally

```sh
python -m unittest discover -s profiles/ci -p "test_*.py"
```
