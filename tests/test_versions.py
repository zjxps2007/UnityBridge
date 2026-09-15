"""Release ordering shared by Python metadata, standalone builds, and Unity."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unity_bridge._cli.versions import version_status


class VersionTests(unittest.TestCase):
    def test_python_and_unity_prerelease_spellings_are_equivalent(self) -> None:
        for current, latest in [
            ("0.2.2rc1", "0.2.2-rc.1"),
            ("0.2.2a2", "v0.2.2-alpha.2"),
            ("0.2.2b3", "0.2.2-beta.3"),
            ("0.2.2RC1", "0.2.2-rc.1+build.42"),
            ("0.2", "0.2.0"),
            ("0.2.2", "v0.2.2+build.42"),
        ]:
            with self.subTest(current=current, latest=latest):
                self.assertEqual(version_status(current, latest), "current")

    def test_prereleases_sort_before_the_final_release(self) -> None:
        ordered = ["0.2.1", "0.2.2-alpha.1", "0.2.2-beta.1", "0.2.2-rc.1", "0.2.2-rc.2", "0.2.2-rc.10", "0.2.2"]
        for earlier, later in zip(ordered, ordered[1:]):
            with self.subTest(earlier=earlier, later=later):
                self.assertEqual(version_status(earlier, later), "outdated")
                self.assertEqual(version_status(later, earlier), "newer")

    def test_release_numbers_take_precedence_over_prerelease_stage(self) -> None:
        for current, latest in [("0.2.2", "0.2.3rc1"), ("0.2.9", "0.3.0a1"), ("0.9.9", "1.0.0a1")]:
            with self.subTest(current=current, latest=latest):
                self.assertEqual(version_status(current, latest), "outdated")

    def test_unrecognized_versions_do_not_invent_an_order(self) -> None:
        for value in ["unknown", "", "branch-123", "0.2.2-garbage", "0.2.2rc1oops"]:
            with self.subTest(value=value):
                self.assertEqual(version_status(value, "0.2.2"), "unknown")
                self.assertEqual(version_status("0.2.2", value), "unknown")


if __name__ == "__main__":
    unittest.main()
