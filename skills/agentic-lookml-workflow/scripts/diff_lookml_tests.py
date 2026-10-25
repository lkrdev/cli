"""Extract added or modified LookML `test:` blocks between a base git ref and HEAD."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def extract_test_blocks(src: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    pos = 0
    for m in re.finditer(r"(?m)^\s*test:\s*([A-Za-z0-9_]+)\s*\{", src):
        if m.start() < pos:
            continue
        depth, i, quote_char, in_cmt = 0, m.end() - 1, "", False
        while i < len(src):
            c = src[i]
            if in_cmt:
                in_cmt = c != "\n"
            elif quote_char:
                if c == "\\" and i + 1 < len(src):
                    i += 1
                elif c == quote_char:
                    quote_char = ""
            elif c == "#":
                in_cmt = True
            elif c in ('"', "'"):
                quote_char = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    blocks[m.group(1)] = src[m.start() : i + 1]
                    pos = i + 1
                    break
            i += 1
    return blocks


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return res.stdout if res.returncode == 0 else ""


def main(base_ref: str) -> tuple[str, str]:
    pairs: list[tuple[str, str]] = []
    for raw in _git("diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD", "--", "*.test.lkml").splitlines():
        if not (p := raw.strip()) or not Path(p).is_file():
            continue
        fid = re.sub(r"^(?:\./)?data/[^/]+/lookml/", "", p)
        base_blocks = extract_test_blocks(_git("show", f"{base_ref}:{p}") or _git("show", f"{base_ref}:{fid}"))
        pairs.extend((fid, n) for n, b in extract_test_blocks(Path(p).read_text(encoding="utf-8")).items() if base_blocks.get(n) != b)
    return ",".join(f for f, _ in pairs), ",".join(t for _, t in pairs)


if __name__ == "__main__":
    print("\n".join(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main")))
