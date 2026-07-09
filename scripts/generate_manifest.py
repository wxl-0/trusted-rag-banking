"""一次性脚本：从数据集目录自动生成 data/manifest.json"""
import os
import re
import json

DATA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "raw",
        "nfra_page_attachments_500",
    )
).replace("\\", "/")

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.json")


def main():
    files = sorted(os.listdir(DATA_DIR))
    entries = []

    for fname in files:
        name_no_ext, _ = os.path.splitext(fname)
        num = fname.split("_", 1)[0]

        # 取最后一个下划线之后的部分作为标题
        last_us = name_no_ext.rfind("_")
        title = name_no_ext[last_us + 1 :] if last_us > 0 else name_no_ext

        year_match = re.search(r"(20\d{2})", title)
        publish_date = f"{year_match.group(1)}-01-01" if year_match else ""

        entries.append(
            {
                "doc_id": f"NFRA-{num}",
                "title": title,
                "issuer": "国家金融监督管理总局",
                "doc_no": "",
                "publish_date": publish_date,
                "source_url": "",
                "local_path": f"{DATA_DIR}/{fname}",
            }
        )

    out = os.path.abspath(OUT_PATH)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"写入 {len(entries)} 条 → {out}")
    for e in entries[:3]:
        print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
