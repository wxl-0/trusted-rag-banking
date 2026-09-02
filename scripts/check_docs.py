"""Validate the public Markdown documentation without external dependencies."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "CONTEXT.md", ROOT / "AGENTS.md"]
    files.extend((ROOT / "docs").rglob("*.md"))
    return sorted(path for path in files if path.is_file())


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line != line.rstrip():
            errors.append(f"{path.relative_to(ROOT)}:{line_number}: 行尾包含空白字符")

    if sum(1 for line in text.splitlines() if line.lstrip().startswith("```")) % 2:
        errors.append(f"{path.relative_to(ROOT)}: Markdown 代码围栏未成对")

    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = target.split("#", 1)[0].strip("<>")
        if not target:
            continue
        resolved = (path.parent / unquote(target)).resolve()
        if not resolved.exists():
            errors.append(
                f"{path.relative_to(ROOT)}: 相对链接不存在: {match.group(1)}"
            )

    return errors


def main() -> int:
    errors = [error for path in markdown_files() for error in check_file(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"文档检查通过：{len(markdown_files())} 个 Markdown 文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
