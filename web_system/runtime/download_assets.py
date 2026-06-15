#!/usr/bin/env python3
"""Download runtime model assets defined in assets_manifest.json."""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().with_name("assets_manifest.json")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ppt-narration-agent/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        target.write_bytes(response.read())


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for asset in data.get("assets", []):
        target = ROOT / asset["path"]
        expected_sha256 = asset.get("sha256", "")
        url = asset.get("url")
        if not url:
            print(f"skip {asset['path']}: missing url", file=sys.stderr)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and expected_sha256 and sha256_of(target) == expected_sha256:
            print(f"skip {asset['path']}")
            continue

        print(f"download {asset['path']}")
        download(url, target)

        if expected_sha256:
            actual_sha256 = sha256_of(target)
            if actual_sha256 != expected_sha256:
                target.unlink(missing_ok=True)
                print(f"sha256 mismatch for {asset['path']}", file=sys.stderr)
                print(f"expected: {expected_sha256}", file=sys.stderr)
                print(f"actual:   {actual_sha256}", file=sys.stderr)
                return 1

    print("runtime assets are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
