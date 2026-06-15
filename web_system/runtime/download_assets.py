#!/usr/bin/env python3
"""Download external runtime assets listed in assets_manifest.json.

Usage:
  cd web_system/runtime
  python3 download_assets.py

Before running, fill each asset's cos_url in assets_manifest.json.
"""
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


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assets = data.get("assets", [])
    missing_urls = [asset["path"] for asset in assets if not asset.get("cos_url")]
    if missing_urls:
        print("以下资产还没有填写 cos_url，请先上传到腾讯云 COS 后回填：")
        for path in missing_urls:
            print(f"- {path}")
        return 2

    for asset in assets:
        target = ROOT / asset["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_sha256 = asset.get("sha256", "")
        if target.exists() and expected_sha256 and sha256_of(target) == expected_sha256:
            print(f"skip {asset['path']} already exists")
            continue

        print(f"download {asset['path']}")
        with urllib.request.urlopen(asset["cos_url"], timeout=120) as response:
            target.write_bytes(response.read())

        if expected_sha256:
            actual_sha256 = sha256_of(target)
            if actual_sha256 != expected_sha256:
                target.unlink(missing_ok=True)
                print(f"sha256 mismatch for {asset['path']}", file=sys.stderr)
                print(f"expected: {expected_sha256}", file=sys.stderr)
                print(f"actual:   {actual_sha256}", file=sys.stderr)
                return 1

    print("all assets downloaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
