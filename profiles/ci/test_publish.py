import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import struct
from unittest.mock import patch

import publish


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def archive(self, members, receipt=None):
        path = self.root / "windows.tar.gz"
        with tarfile.open(path, "w:gz") as bundle:
            for name, data, kind in members:
                item = tarfile.TarInfo(name)
                if kind == "file":
                    item.size = len(data)
                    bundle.addfile(item, io.BytesIO(data))
                else:
                    item.type = tarfile.SYMTYPE
                    item.linkname = data
                    bundle.addfile(item)
            if receipt is not None:
                data = json.dumps(receipt).encode()
                item = tarfile.TarInfo("manifest.json")
                item.size = len(data)
                bundle.addfile(item, io.BytesIO(data))
        path.with_suffix(".gz.sha256").write_text(publish.digest(path) + "  " + path.name)
        return path

    def test_an_artifact_from_a_different_source_cannot_be_imported(self):
        archive = self.archive([], {"platform": "windows", "identity": {"plan": "different"}})
        with self.assertRaisesRegex(ValueError, "Different source"):
            publish.import_bundle(archive, self.root / "source", {"plan": "expected"}, "windows")

    def windows_bundle(self, changed=False):
        prefix = publish.CONFIG["platforms"]["windows"]["binary_path"]
        bundle_root = self.root / "payload" / prefix
        for relative in ("include/ffmpegkit_c.h", "lib/ffmpegkit.lib", "licenses/license.txt",
                         "lib/cmake/ffmpeg-kit-next/ffmpeg-kit-next-config.cmake"):
            destination = bundle_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('FFMPEG_KIT_NEXT_VERSION "9.0.2"')
        (bundle_root / "bin").mkdir()
        for component in publish.COMPONENTS:
            data = bytearray(72)
            struct.pack_into("<I", data, 0x3c, 64)
            data[64:68] = b"PE\0\0"
            struct.pack_into("<H", data, 68, 0x8664)
            (bundle_root / "bin" / f"{component.removeprefix('lib')}-1.dll").write_bytes(data)
        identity = {"plan": {"wrapper_version": "9.0.2"}, "prepared_tree": "expected"}
        receipt = {"identity": identity, "platform": "windows", "files": publish.manifest(bundle_root)}
        if changed:
            (bundle_root / "include/ffmpegkit_c.h").write_text("changed after certification")
        archive = self.root / "valid.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(bundle_root, arcname=prefix)
            data = json.dumps(receipt).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        archive.with_suffix(".gz.sha256").write_text(publish.digest(archive) + "  " + archive.name)
        return archive, identity, prefix

    def test_a_certified_bundle_survives_tar_transfer(self):
        archive, identity, prefix = self.windows_bundle()
        receipt = publish.import_bundle(archive, self.root / "assembled", identity, "windows")
        self.assertEqual(publish.manifest(self.root / "assembled" / prefix), receipt["files"])

    def test_replacing_a_native_file_cannot_be_hidden_by_recomputing_the_tar_checksum(self):
        archive, identity, prefix = self.windows_bundle(changed=True)
        with self.assertRaisesRegex(ValueError, "modified"):
            publish.import_bundle(archive, self.root / "assembled", identity, "windows")
        self.assertFalse((self.root / "assembled" / prefix).exists())

    def test_a_modified_archive_is_rejected_before_extraction(self):
        archive = self.archive([], {})
        with archive.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            publish.import_bundle(archive, self.root / "source", {}, "windows")

    def test_an_archive_cannot_write_outside_the_native_bundle(self):
        archive = self.archive([("../outside.txt", b"data", "file")], {})
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            publish.import_bundle(archive, self.root / "source", {}, "windows")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_an_archive_cannot_replace_the_manifest_with_a_duplicate(self):
        archive = self.archive([("manifest.json", b"{}", "file")], {})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            publish.import_bundle(archive, self.root / "source", {}, "windows")

    def test_a_symbolic_link_cannot_escape_the_native_bundle(self):
        bundle = self.root / "native"
        bundle.mkdir()
        (self.root / "outside").write_text("private")
        try:
            (bundle / "escape").symlink_to(self.root / "outside")
        except OSError:
            self.skipTest("This host cannot create symbolic links")
        with self.assertRaisesRegex(ValueError, "escapes"):
            publish.manifest(bundle)

    def test_a_mismatched_patched_tree_is_not_silently_built(self):
        source = self.root / "source"
        source.mkdir()
        with patch.object(publish, "git", return_value="another-commit"):
            with self.assertRaisesRegex(ValueError, "pinned upstream"):
                publish.prepare(source, {"upstream_sha": "expected"})

    def test_a_patch_conflict_requires_review_instead_of_being_skipped(self):
        source = self.root / "source"
        source.mkdir()
        failed = type("Result", (), {"returncode": 1, "stderr": "conflict"})()
        with patch.object(publish, "git", side_effect=["expected", ""]), \
                patch.object(publish, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "Review/rebase"):
                publish.prepare(source, {"upstream_sha": "expected"})

    def test_existing_tags_are_rejected_before_resolving_or_building_upstream(self):
        with patch.object(publish, "remote_tag", return_value=True), patch.object(publish, "api") as api:
            with self.assertRaisesRegex(ValueError, "already exists"):
                publish.plan_release("v9.0.2", 1, self.root)
            api.assert_not_called()

    def test_automatic_build_number_follows_the_highest_matching_tag(self):
        tags = [{"ref": "refs/tags/v9.0.2-studio.2"},
                {"ref": "refs/tags/v9.0.2-studio.10"},
                {"ref": "refs/tags/v9.0.2-studio.99-preview"}]
        with patch.object(publish, "api", return_value=tags), \
                patch.object(publish, "remote_tag", return_value=True) as exists:
            with self.assertRaisesRegex(ValueError, "already exists"):
                publish.plan_release("v9.0.2", 0, self.root)
            exists.assert_called_once_with(publish.CONFIG["repository"], "v9.0.2-studio.11")

    def test_a_network_failure_is_not_treated_as_an_available_tag(self):
        failed = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "TLS timeout"})()
        with patch.object(publish, "run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "Cannot check"):
                publish.remote_tag("owner/repository", "v9.0.2-studio.1")

    def test_a_changed_tooling_checkout_cannot_reuse_an_old_plan(self):
        publish.save(self.root / "plan.json", {"inputs": {}, "control_sha": "expected"})
        with patch.object(publish, "inputs", return_value={}), patch.object(publish, "git", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "planned commit"):
                publish.read_plan(self.root)

    def test_remote_tag_content_is_never_overwritten(self):
        plan = {"release_tag": "v9.0.2-studio.1"}
        for platform in publish.CONFIG["platforms"]:
            for suffix in (".tar.gz", ".tar.gz.sha256"):
                (self.root / f"{plan['release_tag']}-{platform}{suffix}").write_text("asset")
        with patch.object(publish, "read_plan", return_value=plan), \
                patch.dict(publish.os.environ, {"GITHUB_REPOSITORY": publish.CONFIG["repository"]}), \
                patch.object(publish, "remote_tag", return_value=True), \
                patch.object(publish, "git", side_effect=["", "local-commit", "local-commit", "", "remote-tree", "local-tree"]) as git, \
                patch.object(publish, "run") as run:
            with self.assertRaisesRegex(ValueError, "never be overwritten"):
                publish.publish(self.root, self.root, "publish")
            self.assertFalse(any(call.args[1] == "push" for call in git.call_args_list))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
