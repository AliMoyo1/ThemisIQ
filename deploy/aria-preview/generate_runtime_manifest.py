#!/usr/bin/env python3
"""Generate the immutable ARIA preview worker runtime manifest at image build."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
from pathlib import Path


def _output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def _package_version(name: str) -> str:
    return _output(["dpkg-query", "-W", "-f=${Version}", name])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--worker-build-id", required=True)
    parser.add_argument("--built-at", required=True)
    args = parser.parse_args()

    if "@sha256:" not in args.base_image:
        raise SystemExit("--base-image must be an immutable digest reference")
    for name, value in (
        ("worker build id", args.worker_build_id),
        ("build timestamp", args.built_at),
    ):
        if not value.strip() or "FILL_" in value.upper() or "PIN_ME" in value.upper():
            raise SystemExit(f"{name} must be a real build value")

    manifest = {
        "base_image_digest": args.base_image,
        "libreoffice_version": _output(["soffice", "--version"]),
        "font_package_versions": {
            "fonts-liberation2": _package_version("fonts-liberation2"),
        },
        "package_versions": {
            "libreoffice-writer": _package_version("libreoffice-writer"),
            "python3": _package_version("python3"),
        },
        "worker_build_id": args.worker_build_id,
        "pypdf_version": importlib.metadata.version("pypdf"),
        "built_at": args.built_at,
    }
    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
