"""一次性脚本：从数据集目录自动生成 data/manifest.json"""
import os
import re
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "nfra_page_attachments_500"
OUT_PATH = REPO_ROOT / "data" / "manifest.json"


def extract_titles(filename: str) -> tuple[str, str | None]:
    """从文件名提取 title 和 notice_title。

    文件名格式: 序号_中间部分_最后部分.ext
    - 如果中间部分 ≠ 最后部分 → notice_title=中间部分, title=最后部分
    - 如果中间部分 ≈ 最后部分 → notice_title=None, title=最后部分
    """
    stem, _ = os.path.splitext(filename)
    # 去掉序号前缀
    m = re.match(r"\d+_(.*)", stem)
    if not m:
        return stem, None

    rest = m.group(1)
    last_sep = rest.rfind("_")
    if last_sep <= 0:
        return rest, None

    middle = rest[:last_sep]
    last_part = rest[last_sep + 1:]

    # 判断中间部分和最后部分是否相同/高度相似
    def normalize(s: str) -> str:
        s = re.sub(r"[\s　（）()《》「」　]", "", s)
        s = s.replace("保险", "险").replace("财产", "产")
        return s

    if normalize(middle) == normalize(last_part):
        return last_part, None
    # 如果 normalize 后编辑距离很小（前15字相同），也视为同一标题
    if normalize(middle)[:15] == normalize(last_part)[:15] and abs(len(middle) - len(last_part)) < 5:
        return last_part, None

    # 中间部分是通知标题，最后部分是附件标题
    notice_title = middle.replace("_", " ").strip()
    return last_part, notice_title


def main():
    files = sorted(os.listdir(DATA_DIR))
    entries = []

    for fname in files:
        num = fname.split("_", 1)[0]
        title, notice_title = extract_titles(fname)

        year_match = re.search(r"(20\d{2})", title)
        publish_date = f"{year_match.group(1)}-01-01" if year_match else ""

        local_path = (DATA_DIR / fname).resolve().relative_to(REPO_ROOT).as_posix()

        entry = {
            "doc_id": f"NFRA-{num}",
            "title": title,
            "issuer": "国家金融监督管理总局",
            "doc_no": "",
            "publish_date": publish_date,
            "source_url": "",
            "local_path": local_path,
        }
        if notice_title:
            entry["notice_title"] = notice_title

        entries.append(entry)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    # 统计
    with_notice = sum(1 for e in entries if "notice_title" in e)
    print(f"写入 {len(entries)} 条 → {OUT_PATH}")
    print(f"  其中 {with_notice} 条有 notice_title")
    for e in entries[:3]:
        print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
