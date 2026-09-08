#!/usr/bin/env python3
"""Normalize Graphify hub labels into short, readable community names."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


EXTENSIONS = {
    "dart",
    "js",
    "json",
    "kt",
    "mjs",
    "py",
    "sh",
    "sql",
    "swift",
    "ts",
    "tsx",
}


def normalize(label: str) -> str:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", label)
    words = [
        word
        for word in re.split(r"[^A-Za-z0-9]+", expanded)
        if word and word.lower() not in EXTENSIONS
    ][:5]

    if not words:
        return "Unnamed Component"
    if len(words) >= 2:
        return " ".join(words)

    word = words[0]
    lowered = word.lower()
    if lowered == "main":
        return "Main Entry Point"
    if lowered in {"any", "typedef"}:
        return f"{word} Type"
    return f"{word} Module"


def main() -> None:
    labels_path = Path(sys.argv[1] if len(sys.argv) > 1 else "graphify-out/.graphify_labels.json")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    normalized = {community: normalize(label) for community, label in labels.items()}
    labels_path.write_text(json.dumps(normalized, ensure_ascii=False), encoding="utf-8")
    print(f"Normalized {len(normalized)} Graphify community labels")


if __name__ == "__main__":
    main()

