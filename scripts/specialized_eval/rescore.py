#!/usr/bin/env python
"""Re-score a completed specialized evaluation without calling retrieval or an LLM."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE_ROOT))

from scripts.specialized_eval.run_eval import load_dataset, score_result, summarize


ITEM_FIELDS = (
    "id", "origin", "category", "subtype", "question", "standard_answer",
    "expected_behavior", "critical_entities", "expected_sources", "expected_evidence",
    "forbidden_values", "scoring_rule", "evaluation_status", "evaluation_note",
)


def _resolved(path: Path) -> Path:
    return path if path.is_absolute() else SOURCE_ROOT / path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-report",
        type=Path,
        default=SOURCE_ROOT / "data/eval/runs/specialized-100-v1/report.json",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=SOURCE_ROOT / "data/eval/银行监管RAG专项评测集_100题.xlsx",
    )
    parser.add_argument("--run-name", default="specialized-100-v1-rescored")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    source_path = _resolved(args.source_report)
    dataset_path = _resolved(args.dataset)
    source_bytes = source_path.read_bytes()
    source_report = json.loads(source_bytes)
    items = load_dataset(dataset_path)
    source_results = {row["id"]: row for row in source_report.get("results", [])}
    expected_ids = [item["id"] for item in items]
    if sorted(source_results) != sorted(expected_ids):
        missing = sorted(set(expected_ids) - set(source_results))
        extra = sorted(set(source_results) - set(expected_ids))
        raise RuntimeError(f"源报告题号不完整：missing={missing}, extra={extra}")

    rescored_results = []
    for item in items:
        old = source_results[item["id"]]
        if old.get("error"):
            scoring = old.get("scoring", {})
        else:
            scoring = score_result(item, {
                "behavior": old.get("raw_behavior"),
                "answer": old.get("actual_answer", ""),
                "refuse_reason": old.get("refuse_reason"),
                "evidence": old.get("evidence", []),
            })
        updated = dict(old)
        updated.update({field: item[field] for field in ITEM_FIELDS})
        updated["scoring"] = scoring
        rescored_results.append(updated)

    metrics = summarize(items, rescored_results)
    rescored_at = datetime.now().astimezone().isoformat(timespec="seconds")
    report = {
        "run_name": args.run_name,
        "report_type": "offline_rescore",
        "scoring_version": "2.1",
        "rescored_from": str(source_path),
        "source_report_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "dataset": str(dataset_path),
        "model": source_report.get("model"),
        "started_at": source_report.get("started_at"),
        "completed_at": source_report.get("completed_at"),
        "rescored_at": rescored_at,
        "selected_ids": expected_ids,
        "total": metrics["overall"]["total"],
        "correct": metrics["overall"]["correct"],
        "accuracy": metrics["overall"]["rate"],
        "metrics": metrics,
        "results": rescored_results,
    }

    run_dir = args.run_dir or SOURCE_ROOT / "data/eval/runs" / args.run_name
    run_dir = _resolved(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    published_path = None
    if args.publish:
        published_path = SOURCE_ROOT / "data/eval/specialized_eval_report.json"
        shutil.copyfile(report_path, published_path)
    print(json.dumps({
        "report": str(report_path),
        "published_report": str(published_path) if published_path else None,
        "metrics": metrics,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
