"""Create a private, unsigned offline copy of a local RoboMaster 1.2.0 APK.

Only the exact APK below is supported. Sign the result with Android build-tools.
No vendor binary, credential, account flag, or privacy acceptance is supplied.
"""

import argparse
import copy
import hashlib
import json
import struct
import zipfile
from pathlib import Path


APK_SHA256 = "82c86a9e77c4dbf9fb4c18660b3d0fbbfd6095c4c4b0eb03e9b2c6aae13059a1"
LIB_SHA256 = {
    "arm64-v8a": "04ed17c693dcccda58a450f77d1f6b75713132dc8fdf20213656346b970a884f",
    "armeabi-v7a": "bb74e9ab72ba1f71134ad102858d4389319021b2c61957ecb25ec669857b22f3",
}
BOOTSTRAP_SHA256 = {
    "arm64-v8a": "edde513389823c52a02d45765ce75fcfa7fc7645ace4933e2a9cd3a2808585f7",
    "armeabi-v7a": "afc264717dd57c7e7719a1535c06cfde9ec8acd8ca0ad904d46650ef2c4f0864",
}


def bootstrap_definitions(arch):
    """Local re-signing changes the certificate and ZIP digests checked at boot.

    The pinned protector reverses its code region when loaded. File bytes below
    are therefore reversed instructions. Only certificate/ZIP self-checks are
    adjusted; class loading, Android signature verification and consent remain.
    The complete payload is independently checked when this tool builds it.
    """
    if arch == "arm64-v8a":
        rows = [
            ("local_certificate", 0x43940, "a9bc5ff8", "d65f03c0"),
            ("local_zip_entries", 0x43528, "a9017bfda9be4ff4", "d65f03c052800020"),
            ("local_zip_inventory", 0x42DC4, "a9ba6ffc", "d65f03c0"),
        ]
    elif arch == "armeabi-v7a":
        rows = [
            ("local_certificate", 0x2B22E, "41f0e92d", "bf004770"),
            ("local_zip_entries", 0x2AF0A, "4830e92d", "47702001"),
            ("local_zip_inventory", 0x2AA0E, "4ff0e92d", "bf004770"),
        ]
    else:
        raise ValueError(f"Unsupported ABI: {arch}")
    return [(n, o, bytes.fromhex(b), bytes.fromhex(a)) for n, o, b, a in rows]


def patch_bootstrap(data, arch):
    if hashlib.sha256(data).hexdigest() != BOOTSTRAP_SHA256[arch]:
        raise ValueError(f"Unknown or already modified {arch} bootstrap library")
    result = bytearray(data)
    for name, offset, before, after in bootstrap_definitions(arch):
        if data[offset:offset + len(before)] != before or len(before) != len(after):
            raise ValueError(f"Unexpected bootstrap layout: {arch}/{name}")
        result[offset:offset + len(after)] = after
    return bytes(result)


def branch(arch, source, target, link=False):
    displacement = target - source - (8 if arch == "armeabi-v7a" else 0)
    bits = 24 if arch == "armeabi-v7a" else 26
    if displacement % 4 or not -(1 << (bits + 1)) <= displacement < (1 << (bits + 1)):
        raise ValueError("Unaligned or out-of-range branch")
    opcode = (0xEB000000 if link else 0xEA000000) if bits == 24 else (0x94000000 if link else 0x14000000)
    return struct.pack("<I", opcode | ((displacement // 4) & ((1 << bits) - 1)))


def patch_definitions(arch):
    """Offsets equal RVAs in these two pinned ELF executable segments."""
    h = bytes.fromhex
    if arch == "arm64-v8a":
        nop = h("1f2003d5")
        # Startup chooses the existing privacy scene until consent is accepted.
        startup = h("e0031faa") + branch(arch, 0xAD095C, 0xACEFD8, True) + h("e803002a") + nop * 3
        # Preserve SP/LR; poll consent, then use the existing menu transition.
        consent = h("fd7bbfa9e0031faa") + branch(arch, 0xAD0C44, 0xACEFD8, True)
        consent += h("fd7bc1a840000034") + branch(arch, 0xAD0C50, 0xAD1504) + h("c0035fd6")
        rows = [
            ("startup_uses_privacy_instead_of_account", 0xAD0958, "28c500b008bd42f9000140f983712494400300b408b04039", startup),
            ("menu_skips_remote_token_check", 0xAD10EC, "a4d2fc97", nop),
            ("invalid_token_returns_to_menu", 0xACF2F4, "e8030032", h("e8031e32")),
            ("logout_returns_to_menu", 0xAD1578, "e8030032", h("e8031e32")),
            ("consent_to_menu_without_login", 0xAD0C3C, "f30f1ef8fd7b01a9fd430091d3cf00b068ce6839e800003728c20090", consent),
            ("poll_existing_privacy_choice", 0xBF4B4C, "c0035fd6", branch(arch, 0xBF4B4C, 0xAD0C3C)),
        ]
    elif arch == "armeabi-v7a":
        nop = h("00f020e3")
        startup = h("0000a0e3") + branch(arch, 0x5DAAA4, 0x5D88AC, True) + nop * 8
        consent = h("10402de90000a0e3") + branch(arch, 0x5DAE88, 0x5D88AC, True)
        consent += h("1040bde8000050e31eff2f01") + branch(arch, 0x5DAE98, 0x5DB978)
        rows = [
            ("startup_uses_privacy_instead_of_account", 0x5DAAA0, "94009fe500009fe7000090e587ec2feb0050a0e1000055e30100001a0000a0e3516cfaeb1800d5e5", startup),
            ("menu_skips_remote_token_check", 0x5DB450, "62befbeb", nop),
            ("invalid_token_returns_to_menu", 0x5D8C50, "0110a0e3", h("0410a0e3")),
            ("logout_returns_to_menu", 0x5DB9F4, "0110a0e3", h("0410a0e3")),
            ("consent_to_menu_without_login", 0x5DAE80, "30482de908b08de208d04de230019fe500008fe00000d0e5000050e3", consent),
            ("poll_existing_privacy_choice", 0x74CDBC, "1eff2fe1", branch(arch, 0x74CDBC, 0x5DAE80)),
        ]
    else:
        raise ValueError(f"Unsupported ABI: {arch}")
    return [(name, offset, h(before), after) for name, offset, before, after in rows]


def patch_library(data, arch):
    if hashlib.sha256(data).hexdigest() != LIB_SHA256[arch]:
        raise ValueError(f"Unknown or already modified {arch} library")
    result = bytearray(data)
    covered = set()
    for name, offset, before, after in patch_definitions(arch):
        if len(before) != len(after) or data[offset:offset + len(before)] != before:
            raise ValueError(f"Unexpected layout: {arch}/{name}")
        region = set(range(offset, offset + len(before)))
        if covered.intersection(region):
            raise ValueError("Overlapping patches")
        covered.update(region)
        result[offset:offset + len(after)] = after
    return bytes(result)


def signature_entry(name):
    upper = name.upper()
    return upper.startswith("META-INF/") and (
        upper == "META-INF/MANIFEST.MF" or upper.endswith((".SF", ".RSA", ".DSA", ".EC"))
        or upper.split("/")[-1].startswith("SIG-")
    )


def create_apk(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.exists():
        raise ValueError("Use a new output path; source and existing outputs are never replaced")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != APK_SHA256:
            raise ValueError("Unsupported APK; expected the original RoboMaster 1.2.0 (382)")
    replacements = {}
    report = {"revision": 2, "source_sha256": APK_SHA256, "signed": False, "hardware_validated": False,
              "libraries": {}, "bootstrap_libraries": {}}
    with zipfile.ZipFile(source) as original:
        names = original.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        for arch in LIB_SHA256:
            name = f"lib/{arch}/libil2cpp.so"
            replacements[name] = patch_library(original.read(name), arch)
            report["libraries"][arch] = {
                "original_sha256": LIB_SHA256[arch],
                "patched_sha256": hashlib.sha256(replacements[name]).hexdigest(),
                "patches": [{"name": n, "offset": hex(o), "before": b.hex(), "after": a.hex()}
                            for n, o, b, a in patch_definitions(arch)],
            }
            name = f"lib/{arch}/libbaiduprotect.so"
            replacements[name] = patch_bootstrap(original.read(name), arch)
            report["bootstrap_libraries"][arch] = {
                "original_sha256": BOOTSTRAP_SHA256[arch],
                "patched_sha256": hashlib.sha256(replacements[name]).hexdigest(),
                "patches": [{"name": n, "offset": hex(o), "before": b.hex(), "after": a.hex()}
                            for n, o, b, a in bootstrap_definitions(arch)],
            }
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x") as target:
            for entry in original.infolist():
                if signature_entry(entry.filename):
                    continue
                # Keep contents and compression methods; zipalign regenerates alignment.
                info = copy.copy(entry)
                info.extra = b""
                target.writestr(info, replacements.get(entry.filename, original.read(entry)))
    # Independent, complete payload comparison before signing.
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as target:
        expected = {n for n in original.namelist() if not signature_entry(n)}
        if set(target.namelist()) != expected or target.testzip() is not None:
            raise ValueError("Output ZIP integrity check failed")
        changed = []
        for name in sorted(expected):
            before, after = original.read(name), target.read(name)
            if before != after:
                changed.append(name)
                if name not in replacements or after != replacements[name]:
                    raise ValueError(f"Unexpected payload change: {name}")
        if set(changed) != set(replacements):
            raise ValueError("Missing library patch")
    report["payload_entries_verified"] = len(expected)
    report["changed_entries"] = changed
    with output.open("rb") as stream:
        report["unsigned_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    output.with_suffix(".audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(create_apk(args.source, args.output), indent=2))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f"ERROR: {error}\n")
