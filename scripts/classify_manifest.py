#!/usr/bin/env python
"""
根据文件名/后缀/关键词自动为 manifest.json 填充 parse_profile 字段。
用法：
    python scripts/classify_manifest.py            # 写入 manifest.json
    python scripts/classify_manifest.py --dry-run  # 只打印统计，不写入
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

MANIFEST_PATH = Path(os.environ.get("MANIFEST_PATH", "data/manifest.json"))


def classify(entry: dict) -> str:
    suffix = Path(entry["local_path"]).suffix.lower()
    title = entry.get("title", "")

    if suffix in (".xls", ".xlsx"):
        # 最新版日程表含指标解释和机构范围解释，保留为 data
        if entry.get("doc_id") == "NFRA-010":
            return "data"
        # 签章页无实际数据
        if entry.get("doc_id") == "NFRA-449":
            return "skip"
        if any(kw in title for kw in ("模板", "计算模板", "日程表", "日程", "监管统计", "统计报表")):
            return "skip"
        if "统计表" in title and "情况" not in title:
            return "skip"
        return "data"

    if suffix == ".pdf":
        # 纯文字说明文档，pdfplumber 无表格可提取
        if entry.get("doc_id") == "NFRA-361":
            return "regulation"
        if any(kw in title for kw in ("统计", "汇总表", "数据汇总")):
            return "pdf_table"
        if any(kw in title for kw in ("年报", "报告", "annual", "Annual", "Report")):
            return "report"
        return "regulation"

    if suffix in (".doc", ".docx"):
        return "regulation"

    return "regulation"


def main():
    dry_run = "--dry-run" in sys.argv

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    stats = Counter()

    for entry in manifest:
        if "parse_profile" in entry:
            stats[entry["parse_profile"]] += 1
            continue
        profile = classify(entry)
        entry["parse_profile"] = profile
        stats[profile] += 1

    print("=== parse_profile 分类统计 ===")
    for profile, count in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {profile}: {count}")
    print(f"  总计: {sum(stats.values())}")

    if dry_run:
        print("\n[dry-run] 未写入文件。")
    else:
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n已写入 {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
