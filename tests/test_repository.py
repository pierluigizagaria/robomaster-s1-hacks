#!/usr/bin/env python3
"""Public repository layout, documentation, and product-safety checks."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
ABSOLUTE_USER_PATH_RE = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE)
IGNORED_PARTS = {".git", ".pio", "__pycache__", ".pytest_cache"}


def public_files() -> list[Path]:
    return [
        path.relative_to(ROOT)
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_PARTS or part.startswith("build") for part in path.parts)
    ]


class PublicRepositoryTests(unittest.TestCase):
    def test_version_and_required_entry_points(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "2.0.0")
        required = (
            "README.md",
            "LICENSE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "xt30-battery/README.md",
            "xt30-battery/src/worker.py",
            "xt30-battery/scripts/xt30_battery.py",
            "root-adb/README.md",
            "root-adb/scripts/enable_root_adb.py",
            "windows-offline/README.md",
            "windows-offline/scripts/patch_robomaster_windows.ps1",
            "docs/SAFETY.md",
            "tests/run.ps1",
        )
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_private_roots_are_absent(self) -> None:
        forbidden = {
            ".local",
            "archive",
            "artifacts",
            "captures",
            "firmware-analysis",
            "lab",
            "private",
            "products",
            "repo",
            "test-kit",
            "tools",
        }
        roots = {path.name for path in ROOT.iterdir() if path.is_dir()}
        self.assertTrue(forbidden.isdisjoint(roots), forbidden.intersection(roots))

    def test_markdown_local_links(self) -> None:
        checked = 0
        for path in ROOT.rglob("*.md"):
            if any(part in IGNORED_PARTS or part.startswith("build") for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
            for raw_target in LINK_RE.findall(text):
                target = raw_target.strip().strip("<>")
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not target:
                    continue
                resolved = (path.parent / target).resolve()
                resolved.relative_to(ROOT.resolve())
                self.assertTrue(
                    resolved.exists(),
                    f"broken link in {path.relative_to(ROOT)}: {target}",
                )
                checked += 1
        self.assertGreater(checked, 10)

    def test_public_text_has_no_user_specific_path(self) -> None:
        text_suffixes = {".md", ".py", ".ps1", ".sh", ".c", ".h", ".txt", ".yml", ".yaml"}
        for relative in public_files():
            if relative.suffix.lower() not in text_suffixes:
                continue
            text = (ROOT / relative).read_text(encoding="utf-8", errors="ignore")
            self.assertIsNone(
                ABSOLUTE_USER_PATH_RE.search(text),
                f"user-specific absolute path in {relative}",
            )

    def test_product_safety_guards_are_present(self) -> None:
        root_adb = (ROOT / "root-adb/scripts/enable_root_adb.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("/system/bin/adb_en.sh", root_adb)
        self.assertIn("service.adb.tcp.port", root_adb)
        self.assertIn("adbd_runs_as_root", root_adb)
        self.assertIn("REBOOT THE ROBOT", root_adb)
        for forbidden in ("mount -o remount", "dd if=", "flash_image", "recovery --update"):
            self.assertNotIn(forbidden, root_adb)

        patch = (ROOT / "windows-offline/scripts/patch_robomaster_windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$originalSha256", patch)
        self.assertIn("$offlinePatchedSha256", patch)
        self.assertIn("Write-AssemblyAtomically", patch)
        self.assertIn("Get-ValidatedBackup", patch)

    def test_battery_product_has_one_complete_entry_point(self) -> None:
        product = ROOT / "xt30-battery"
        self.assertFalse((ROOT / "battery-bypass").exists())
        self.assertFalse((product / "firmware").exists())
        self.assertEqual([p.name for p in (product / "scripts").glob("*.py")],
                         ["xt30_battery.py"])
        readme = (product / "README.md").read_text(encoding="utf-8")
        for mode in ("INSTALL", "STATUS", "DISABLE", "UNINSTALL"):
            self.assertIn(mode, readme)
        self.assertIn("independent BMS", readme)
        self.assertIn("end-to-end hardware acceptance", readme)


if __name__ == "__main__":
    unittest.main()
