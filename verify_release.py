from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    manifest_path = ROOT / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    expected_names = set()
    for entry in manifest["files"]:
        relative = entry["path"]
        expected_names.add(relative)
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"MISSING {relative}")
        elif path.stat().st_size != entry["size"]:
            failures.append(f"SIZE {relative}")
        elif sha256_file(path) != entry["sha256"]:
            failures.append(f"SHA256 {relative}")
    actual_names = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name != "release_manifest.json"
    }
    for extra in sorted(actual_names - expected_names):
        failures.append(f"EXTRA {extra}")

    forbidden = [
        "u11" + "04",
        "tel" + "net",
        "vx" + "works",
        "gand" + "alf",
        "aapx" + "zzzzy",
        "diag:fpga:poke",
    ]
    source_files = list((ROOT / "utility3441x").rglob("*.py")) + [
        ROOT / "3441x_service_utility.py",
        ROOT / "3441x_service_utility_gui.pyw",
    ]
    corpus = "\n".join(path.read_text(encoding="utf-8").lower() for path in source_files)
    for token in forbidden:
        if token in corpus:
            failures.append(f"FORBIDDEN_TOKEN {token}")
    if failures:
        print("RELEASE VERIFY: FAIL")
        print("\n".join(failures))
        return 1
    print(f"RELEASE VERIFY: PASS ({len(expected_names)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
