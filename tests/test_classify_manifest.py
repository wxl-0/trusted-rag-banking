import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.classify_manifest import classify


class TestClassifyRules:
    def test_excel_template_skip(self):
        entry = {"local_path": "data/raw/NFRA-461.xlsx", "title": "NFRA计算模板"}
        assert classify(entry) == "skip"

    def test_excel_data(self):
        entry = {"local_path": "data/raw/stat.xls", "title": "2024年银行业数据"}
        assert classify(entry) == "data"

    def test_pdf_statistics_table(self):
        entry = {"local_path": "data/raw/report.pdf", "title": "2024年银行业统计数据汇总"}
        assert classify(entry) == "pdf_table"

    def test_pdf_annual_report(self):
        entry = {"local_path": "data/raw/annual.pdf", "title": "2023年年报"}
        assert classify(entry) == "report"

    def test_pdf_report_english(self):
        entry = {"local_path": "data/raw/eng.pdf", "title": "Annual Report 2023"}
        assert classify(entry) == "report"

    def test_pdf_regulation(self):
        entry = {"local_path": "data/raw/rule.pdf", "title": "商业银行资本管理办法"}
        assert classify(entry) == "regulation"

    def test_doc_regulation(self):
        entry = {"local_path": "data/raw/rule.doc", "title": "存款保险条例"}
        assert classify(entry) == "regulation"

    def test_docx_regulation(self):
        entry = {"local_path": "data/raw/rule.docx", "title": "银行业监管制度"}
        assert classify(entry) == "regulation"

    def test_xls_template_keyword(self):
        entry = {"local_path": "data/raw/calc.xls", "title": "风险加权资产计算模板"}
        assert classify(entry) == "skip"

    def test_pdf_summary_table(self):
        entry = {"local_path": "data/raw/sum.pdf", "title": "全国银行业金融机构数据汇总表"}
        assert classify(entry) == "pdf_table"


class TestDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        manifest = [
            {"doc_id": "T-001", "local_path": "data/raw/a.pdf", "title": "办法"},
            {"doc_id": "T-002", "local_path": "data/raw/b.xlsx", "title": "模板"},
        ]
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "scripts/classify_manifest.py", "--dry-run"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            env={**__import__("os").environ, "MANIFEST_PATH": str(manifest_path)},
        )
        reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert result.returncode == 0, result.stderr
        assert "dry-run" in result.stdout
        assert "总计: 2" in result.stdout
        assert reloaded == manifest
