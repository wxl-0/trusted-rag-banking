import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REGRESSION_DIR = ROOT / "data" / "eval" / "regression"
DATASET_PATH = REGRESSION_DIR / "bad_cases.jsonl"
HASH_PATH = REGRESSION_DIR / "source_hashes.json"
VERIFICATION_PATH = REGRESSION_DIR / "verification_2026-08-29.json"

pytestmark = pytest.mark.skipif(
    not all(path.is_file() for path in (
        DATASET_PATH,
        HASH_PATH,
        VERIFICATION_PATH,
    )),
    reason="私有 Bad Case 回归资产未包含在仓库中",
)

REQUIRED_FIELDS = {
    "id",
    "title",
    "origin",
    "scenario",
    "history",
    "question",
    "expected",
    "observed",
    "classification",
    "lifecycle",
    "regression",
}
ORIGIN_KINDS = {
    "git_regression_test",
    "official_eval_report",
    "specialized_eval_report",
    "manual_observation",
}
LAYERS = {
    "parsing",
    "source_scope",
    "retrieval",
    "query_context",
    "generation",
    "calculation",
    "normalization",
    "admission_control",
    "evaluation_adapter",
}
STATUSES = {"fixed", "snapshot_failed", "open"}
MODES = {
    "pytest",
    "official_eval",
    "specialized_eval",
    "pending_automation",
}
FORBIDDEN_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "object_key",
    "object_bucket",
    "minio_url",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?:password|secret)\s*[=:]", re.IGNORECASE),
)


def _load_cases():
    lines = [line for line in DATASET_PATH.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from _walk(item)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_bad_case_dataset_has_stable_shape_and_unique_ids():
    cases = _load_cases()

    assert len(cases) == 26
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert set(case) == REQUIRED_FIELDS
        assert re.fullmatch(r"[A-Z0-9-]+", case["id"])
        assert case["origin"]["kind"] in ORIGIN_KINDS
        assert case["classification"]["layer"] in LAYERS
        assert case["classification"]["failure_mode"]
        assert case["lifecycle"]["status"] in STATUSES
        assert case["regression"]["mode"] in MODES
        assert case["question"]
        assert case["expected"]["behavior"]
        assert case["expected"]["required_evidence"]
        assert case["observed"]["behavior"]
        assert case["regression"]["assertions"]

    assert Counter(case["lifecycle"]["status"] for case in cases) == {
        "fixed": 5,
        "snapshot_failed": 18,
        "open": 3,
    }
    assert Counter(case["origin"]["kind"] for case in cases) == {
        "git_regression_test": 5,
        "official_eval_report": 8,
        "specialized_eval_report": 10,
        "manual_observation": 3,
    }


def test_report_cases_match_committed_failure_snapshots():
    cases = _load_cases()
    reports = {}

    for case in cases:
        origin = case["origin"]
        if origin["kind"] not in {
            "official_eval_report",
            "specialized_eval_report",
        }:
            continue
        artifact = origin["artifact"]
        if artifact not in reports:
            report = json.loads((ROOT / artifact).read_text())
            reports[artifact] = {item["id"]: item for item in report["results"]}
        source = reports[artifact][origin["case_id"]]
        assert source["question"] == case["question"]
        if origin["kind"] == "official_eval_report":
            assert source["is_correct"] is False
            assert case["regression"]["mode"] == "official_eval"
        else:
            assert source["scoring"]["is_correct"] is False
            assert case["regression"]["mode"] == "specialized_eval"
            assert "--publish" not in case["regression"]["command"]


def test_fixed_cases_reference_existing_tests_and_full_commits():
    for case in _load_cases():
        lifecycle = case["lifecycle"]
        if lifecycle["status"] != "fixed":
            assert lifecycle["repair_commit"] is None
            continue

        assert re.fullmatch(r"[0-9a-f]{40}", lifecycle["repair_commit"])
        assert case["origin"]["snapshot_commit"] == lifecycle["repair_commit"]
        assert case["regression"]["mode"] == "pytest"
        assert case["regression"]["tests"]
        for node_id in case["regression"]["tests"]:
            relative_path, test_name = node_id.split("::", 1)
            test_path = ROOT / relative_path
            assert test_path.is_file()
            assert f"def {test_name}(" in test_path.read_text()


def test_regression_dataset_does_not_change_upstream_eval_assets():
    expected_hashes = json.loads(HASH_PATH.read_text())

    assert set(expected_hashes) == {
        "data/eval/QA数据.xlsx",
        "data/eval/eval_report.json",
        "data/eval/银行监管RAG专项评测集_100题.xlsx",
        "data/eval/specialized_eval_report.json",
    }
    for relative_path, expected_hash in expected_hashes.items():
        assert _sha256(ROOT / relative_path) == expected_hash


def test_bad_case_dataset_excludes_secrets_and_private_object_addresses():
    cases = _load_cases()

    for case in cases:
        for key, value in _walk(case):
            if key is not None:
                assert key.lower() not in FORBIDDEN_KEYS
            if isinstance(value, str):
                assert all(not pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS)


def test_latest_verification_covers_its_snapshot_cases_and_clean_baseline():
    cases = _load_cases()
    verification = json.loads(VERIFICATION_PATH.read_text())
    results = verification["results"]

    assert len(results) == 24
    assert {result["id"] for result in results} < {case["id"] for case in cases}
    assert Counter(result["outcome"] for result in results) == {
        "passed": 12,
        "failed": 12,
    }
    assert verification["summary"] == {
        "cases": 24,
        "passed": 12,
        "failed": 12,
        "execution_errors": 0,
        "historical_snapshot_cases_now_passed": 7,
        "historical_snapshot_cases_still_failed": 11,
    }

    baseline = verification["baseline"]
    assert baseline["knowledge_documents"] == 0
    assert baseline["uploaded_objects"] == 0
    assert baseline["uploaded_vector_points"] == 0
    assert baseline["qdrant"]["regulations"]["points"] == 8945
    assert baseline["qdrant"]["tables"]["points"] == 29561
    assert baseline["bm25"]["chunks"] == 38506
