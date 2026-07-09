"""一次性脚本：从数据集目录自动生成 data/manifest.json"""
import os
import re
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "nfra_page_attachments_500"
OUT_PATH = REPO_ROOT / "data" / "manifest.json"


def main():
    files = sorted(os.listdir(DATA_DIR))
    entries = []

    for fname in files:
        name_no_ext, _ = os.path.splitext(fname)
        num = fname.split("_", 1)[0]

        last_us = name_no_ext.rfind("_")
        title = name_no_ext[last_us + 1 :] if last_us > 0 else name_no_ext

        year_match = re.search(r"(20\d{2})", title)
        publish_date = f"{year_match.group(1)}-01-01" if year_match else ""

        local_path = (DATA_DIR / fname).resolve().relative_to(REPO_ROOT).as_posix()

        entries.append(
            {
                "doc_id": f"NFRA-{num}",
                "title": title,
                "issuer": "国家金融监督管理总局",
                "doc_no": "",
                "publish_date": publish_date,
                "source_url": "",
                "local_path": local_path,
            }
        )

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"写入 {len(entries)} 条 → {OUT_PATH}")
    for e in entries[:3]:
        print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
