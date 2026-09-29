"""Execute pinned ARM login transitions in Unicorn, without a robot or Android.

Usage: python android-offline/scripts/verify_original_android_offline.py ORIGINAL.apk
Requires the locally installed unicorn package. Vendor bytes stay in the APK.
"""

import hashlib
import importlib.util
import struct
import sys
import unittest
import zipfile
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X19, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("patcher", ROOT / "android-offline/scripts/patch_original_android_offline.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
APK = Path(sys.argv.pop(1))
LIBS = {}
BOOTSTRAPS = {}
with zipfile.ZipFile(APK) as archive:
    for abi in patcher.LIB_SHA256:
        original = archive.read(f"lib/{abi}/libil2cpp.so")
        LIBS[abi] = (original, patcher.patch_library(original, abi))
        original_bootstrap = archive.read(f"lib/{abi}/libbaiduprotect.so")
        BOOTSTRAPS[abi] = (original_bootstrap, patcher.patch_bootstrap(original_bootstrap, abi))

CONFIG = {
    "arm64-v8a": dict(arch=UC_ARCH_ARM64, r0=UC_ARM64_REG_X0, r1=UC_ARM64_REG_X1, saved=UC_ARM64_REG_X19,
        sp=UC_ARM64_REG_SP, lr=UC_ARM64_REG_LR, pc=UC_ARM64_REG_PC, pointer=8,
        startup=0xAD0958, choices={0xAD0978: 4, 0xAD0994: 1}, privacy=0xACEFD8,
        poll=0xBF4B4C, helper=0xAD0C3C, logout=0xAD1504, token=0xACF2F4,
        logout_value=0xAD1578, menu_check=0xAD10EC, remote=0xA05B7C),
    "armeabi-v7a": dict(arch=UC_ARCH_ARM, r0=UC_ARM_REG_R0, r1=UC_ARM_REG_R1, saved=UC_ARM_REG_R4,
        sp=UC_ARM_REG_SP, lr=UC_ARM_REG_LR, pc=UC_ARM_REG_PC, pointer=4,
        startup=0x5DAAA0, choices={0x5DAAD4: 4, 0x5DAAEC: 1}, privacy=0x5D88AC,
        poll=0x74CDBC, helper=0x5DAE80, logout=0x5DB978, token=0x5D8C50,
        logout_value=0x5DB9F4, menu_check=0x5DB450, remote=0x4CADE0),
}


class OfflineTransitions(unittest.TestCase):
    def test_resigned_bootstrap_returns_without_terminating_process(self):
        # Reproduce the protector's reversed code mapping, then execute each
        # modified function entry. ARMv7 uses Thumb, unlike IL2CPP above.
        layout = {
            "arm64-v8a": (0x96D0, 0x5CEDC, (0x22C68, 0x2307C, 0x237E4)),
            "armeabi-v7a": (0x4681, 0x3E8BD, (0x17D0C, 0x18030, 0x1852C)),
        }
        for abi, (start, end, entries) in layout.items():
            original, patched = BOOTSTRAPS[abi]
            allowed = {i for _, off, before, _ in patcher.bootstrap_definitions(abi)
                       for i in range(off, off + len(before))}
            self.assertTrue({i for i, (a, b) in enumerate(zip(original, patched)) if a != b} <= allowed)
            decoded = bytearray(patched)
            decoded[start:end] = decoded[start:end][::-1]
            c = CONFIG[abi]
            for index, entry in enumerate(entries):
                with self.subTest(abi=abi, function=index):
                    u = Uc(c["arch"], UC_MODE_ARM)
                    u.mem_map(0, 0x100000)
                    u.mem_write(0, bytes(decoded))
                    u.reg_write(c["sp"], 0xF0000)
                    u.reg_write(c["lr"], 0xF1000)
                    u.reg_write(c["r0"], 0xBAD)
                    u.reg_write(c["saved"], 0xBEEF)
                    u.emu_start(entry | (abi == "armeabi-v7a"), 0xF1000, count=8)
                    self.assertEqual(u.reg_read(c["pc"]), 0xF1000)
                    self.assertEqual(u.reg_read(c["sp"]), 0xF0000)
                    self.assertEqual(u.reg_read(c["saved"]), 0xBEEF)
                    self.assertEqual(u.reg_read(c["r0"]), 1 if index == 1 else 0xBAD)

    def test_bootstrap_rejects_unknown_or_already_patched_input(self):
        for abi, (original, patched) in BOOTSTRAPS.items():
            for data in (patched, original[:-1]):
                with self.assertRaises(ValueError):
                    patcher.patch_bootstrap(data, abi)

    def machine(self, abi, consent):
        c = CONFIG[abi]
        u = Uc(c["arch"], UC_MODE_ARM)
        u.mem_map(0, 0x3000000)
        u.mem_write(0, LIBS[abi][1])
        u.mem_map(0x5000000, 0x3000)
        u.reg_write(c["sp"], 0x5002000)
        u.reg_write(c["lr"], 0x5002800)
        u.reg_write(c["saved"], 0x5000100)
        u.mem_write(0x5000100 + c["pointer"] * 2, (0x5000300).to_bytes(c["pointer"], "little"))
        events = []
        def hook(uc, address, size, user):
            if address == c["privacy"]:
                events.append("read_existing_consent")
                self.assertEqual(uc.reg_read(c["r0"]), 0, "Static method argument must be null")
                uc.reg_write(c["r0"], consent)
                uc.reg_write(c["pc"], uc.reg_read(c["lr"]))
            elif address == c["logout"]:
                events.append("menu")
                uc.emu_stop()
            elif address == 0x5002800:
                events.append("return")
                uc.emu_stop()
            elif address in c["choices"]:
                events.append(c["choices"][address])
                uc.emu_stop()
            elif address == c["remote"]:
                self.fail("Unexpected remote token check")
        u.hook_add(UC_HOOK_CODE, hook)
        return u, c, events

    def test_startup_respects_consent_without_reading_account(self):
        for abi in LIBS:
            for consent in (0, 1):
                with self.subTest(abi=abi, consent=consent):
                    u, c, events = self.machine(abi, consent)
                    u.emu_start(c["startup"], 0, count=100)
                    self.assertEqual(events, ["read_existing_consent", 4 if consent else 1])
                    self.assertEqual(u.reg_read(c["saved"]), 0x5000300)

    def test_first_launch_waits_then_enters_menu_with_stack_and_link_intact(self):
        for abi in LIBS:
            for entry in ("poll", "helper"):
                for consent in (0, 1):
                    with self.subTest(abi=abi, entry=entry, consent=consent):
                        u, c, events = self.machine(abi, consent)
                        u.emu_start(c[entry], 0, count=100)
                        self.assertEqual(events, ["read_existing_consent", "menu" if consent else "return"])
                        self.assertEqual(u.reg_read(c["sp"]), 0x5002000)
                        self.assertEqual(u.reg_read(c["lr"]), 0x5002800)
                        self.assertEqual(u.reg_read(c["saved"]), 0x5000100)

    def test_logout_and_invalid_token_box_menu_state(self):
        for abi in LIBS:
            for entry in ("token", "logout_value"):
                with self.subTest(abi=abi, entry=entry):
                    u, c, _ = self.machine(abi, 1)
                    # Execute the replaced immediate and its original stack store.
                    if abi == "arm64-v8a" and entry == "logout_value":
                        from unicorn.arm64_const import UC_ARM64_REG_X29
                        u.reg_write(UC_ARM64_REG_X29, 0x5002100)
                    u.emu_start(c[entry], c[entry] + 8, count=2)
                    slot = 0x50020FC if abi == "arm64-v8a" and entry == "logout_value" else 0x5002000 + (12 if abi == "arm64-v8a" else 4)
                    self.assertEqual(struct.unpack("<I", u.mem_read(slot, 4))[0], 4)

    def test_menu_remote_call_is_removed(self):
        for abi in LIBS:
            with self.subTest(abi=abi):
                u, c, events = self.machine(abi, 1)
                u.emu_start(c["menu_check"], c["menu_check"] + 4, count=1)
                self.assertEqual(events, [])
                self.assertEqual(u.reg_read(c["lr"]), 0x5002800)

    def test_only_reviewed_bytes_change(self):
        for abi, (original, patched) in LIBS.items():
            with self.subTest(abi=abi):
                restored = bytearray(patched)
                for _, offset, before, after in patcher.patch_definitions(abi):
                    self.assertEqual(patched[offset:offset + len(after)], after)
                    restored[offset:offset + len(before)] = before
                self.assertEqual(hashlib.sha256(restored).hexdigest(), patcher.LIB_SHA256[abi])
                self.assertEqual(restored, original)

    def test_unknown_and_already_patched_libraries_fail_closed(self):
        for abi, (original, patched) in LIBS.items():
            for data in (original[:-1], patched, b"not an ELF"):
                with self.subTest(abi=abi, length=len(data)):
                    with self.assertRaises(ValueError):
                        patcher.patch_library(data, abi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
