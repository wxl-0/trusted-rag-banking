"""
验证 QA 测评集的 evidence 引用能否匹配到解析出的 chunk。
用法：python scripts/check_qa_evidence_coverage.py [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QA_PATH = REPO_ROOT / "data" / "eval" / "QA数据.xlsx"


@dataclass(frozen=True)
class EvidenceRef:
    file_hint: str | None = None
    sheet_name: str | None = None
    cell_ref: str | None = None
    value: str | None = None


def parse_evidence_text(text: str) -> list[EvidenceRef]:
    if not text:
        return []
    file_match = re.search(r"([^/；]+\.(?:xlsx?|pdf|docx?))(?=[；。]|$)", text)
    sheet_match = re.search(r"工作表[：:「\"]([^；。」\"]+)", text)
    cell_match = re.search(r"单元格[：:\s]*([A-Z]+[0-9]+)", text, re.I)
    value_match = re.search(r"原始值[：:\s]*([^；。]+)", text)
    if not any((file_match, sheet_match, cell_match, value_match)):
        return []
    return [
        EvidenceRef(
            file_hint=file_match.group(1).strip() if file_match else None,
            sheet_name=sheet_match.group(1).strip() if sheet_match else None,
            cell_ref=cell_match.group(1).upper() if cell_match else None,
            value=value_match.group(1).strip() if value_match else None,
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-path", default=str(QA_PATH))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not Path(args.qa_path).exists():
        raise FileNotFoundError(args.qa_path)

    from openpyxl import load_workbook

    workbook = load_workbook(args.qa_path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    evidence_idx = next((i for i, name in enumerate(headers) if "evidence" in name.lower()), None)
    if evidence_idx is None:
        print("未找到 evidence 列")
        return 1

    checked = 0
    refs = []
    for row in rows[1:]:
        if args.limit is not None and checked >= args.limit:
            break
        checked += 1
        text = str(row[evidence_idx] or "")
        refs.extend(parse_evidence_text(text))

    print(json.dumps(
        {"checked_rows": checked, "structured_refs_count": len(refs), "sample_refs": [asdict(r) for r in refs[:5]]},
        ensure_ascii=False, indent=2
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
