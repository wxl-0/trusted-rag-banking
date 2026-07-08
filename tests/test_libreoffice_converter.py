from pathlib import Path

from scripts.convert_doc_with_libreoffice import should_skip_existing, target_path_for_doc


def test_target_path_for_doc_uses_doc_id_and_original_stem(tmp_path):
    item = {
        "doc_id": "NFRA-385",
        "local_path": str(tmp_path / "385_sample.doc"),
    }
    target = target_path_for_doc(item, tmp_path / "out")

    assert target == tmp_path / "out" / "NFRA-385_385_sample.docx"


def test_should_skip_existing_respects_force(tmp_path):
    target = tmp_path / "converted.docx"
    target.write_text("cached", encoding="utf-8")

    assert should_skip_existing(target, force=False)
    assert not should_skip_existing(target, force=True)
