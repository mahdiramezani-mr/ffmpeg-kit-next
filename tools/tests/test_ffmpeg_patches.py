import pathlib
import subprocess
import tempfile
import unittest


REPO = pathlib.Path(__file__).resolve().parents[2]
BASE_COMMIT = "3a0867c2bfda4a4d4309ca1a8cbdc6175e67f587"
PATCHED_BLOB = "0e576c15632a39013103e9e3bd093568a4423bcb"


class FFmpegPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = pathlib.Path(self.temp.name) / "ffmpeg"
        self.run_command("git", "clone", "--shared", "--no-checkout", str(REPO / "src/ffmpeg"), str(self.source))
        self.run_command("git", "-C", str(self.source), "checkout", "--detach", BASE_COMMIT)
        self.file = self.source / "libavcodec/h2645_vui.c"

    def run_command(self, *args, check=True):
        return subprocess.run(args, capture_output=True, text=True, check=check)

    def apply_patch(self, check=True):
        return self.run_command("bash", str(REPO / "tools/apply-ffmpeg-patches.sh"), str(self.source), check=check)

    def test_fresh_checkout_matches_the_official_patch_and_changes_only_vui(self):
        self.apply_patch()
        blob = self.run_command("git", "hash-object", str(self.file)).stdout.strip()
        self.assertEqual(blob, PATCHED_BLOB)
        changed = self.run_command("git", "-C", str(self.source), "diff", "--name-only").stdout.strip()
        self.assertEqual(changed, "libavcodec/h2645_vui.c")

    def test_cached_patched_source_is_not_modified_again(self):
        self.apply_patch()
        first = self.file.read_bytes()
        result = self.apply_patch()
        self.assertEqual(self.file.read_bytes(), first)
        self.assertIn("already applied", result.stdout)

    def test_unexpected_source_is_rejected_without_modifying_it(self):
        self.file.write_bytes(self.file.read_bytes() + b"\n")
        before = self.file.read_bytes()
        result = self.apply_patch(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertIn("unexpected", result.stderr)

    def test_source_from_a_different_commit_is_rejected(self):
        self.run_command("git", "-C", str(self.source), "-c", "user.name=Patch Test", "-c", "user.email=patch-test@example.invalid", "commit", "--allow-empty", "-m", "different source revision")
        before = self.file.read_bytes()
        result = self.apply_patch(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertIn("not the pinned n7.1.5", result.stderr)


if __name__ == "__main__":
    unittest.main()
