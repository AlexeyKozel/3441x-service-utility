from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION = "v1.0.0-rc13"
ARCHIVE_STEM = "3441x_service_utility_v1_0_rc13"
TOP_LEVEL_FILES = (
    "3441x_service_utility.py",
    "3441x_service_utility_gui.pyw",
    "README.md",
    "SAFETY.md",
    "CHANGELOG.md",
    "LICENSE",
    "requirements-live.txt",
    "run_cli.bat",
    "run_gui.bat",
    "verify_release.py",
)
DIRECTORIES = ("utility3441x", "docs")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    output_dir = ROOT / "dist" / VERSION
    staging = output_dir / ARCHIVE_STEM
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    for name in TOP_LEVEL_FILES:
        shutil.copy2(ROOT / name, staging / name)
    for name in DIRECTORIES:
        shutil.copytree(
            ROOT / name,
            staging / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    entries = []
    for path in sorted(item for item in staging.rglob("*") if item.is_file()):
        relative = path.relative_to(staging).as_posix()
        entries.append(
            {"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)}
        )
    manifest = {"release": VERSION, "files": entries}
    (staging / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    archive_base = output_dir / ARCHIVE_STEM
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", output_dir, ARCHIVE_STEM))
    archive_hash = sha256_file(archive_path)
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{archive_hash}  {archive_path.name}\n", encoding="ascii"
    )
    print(archive_path)
    print(f"SHA256 {archive_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
