#!/usr/bin/env python
"""
对评测集跑问答，输出 eval_report.json。
用法：python scripts/run_eval.py [--limit N] [--source excel|word|pdf]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from openai import OpenAI

from src.generator.answer_builder import AnswerBuilder

load_dotenv()

QA_PATH = Path("data/eval/QA数据.xlsx")
REPORT_PATH = Path("data/eval/eval_report.json")
PROGRESS_PATH = Path("data/eval/eval_progress.jsonl")


def load_qa_items(source_filter=None):
    """从 QA数据.xlsx 加载选择题，返回列表。"""
    wb = openpyxl.load_workbook(QA_PATH)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    h = {v: i for i, v in enumerate(headers)}

    items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        source_type = row[h["source_type"]]
        if source_filter and source_type != source_filter:
            continue
        items.append(
            {
                "id": row[h["id"]],
                "source_type": source_type,
                "difficulty": row[h["difficulty"]],
                "qa_type": row[h["qa_type"]],
                "question": row[h["question"]],
                "option_a": row[h["option_a"]],
                "option_b": row[h["option_b"]],
                "option_c": row[h["option_c"]],
                "option_d": row[h["option_d"]],
                "answer": row[h["answer"]],          # 正确选项字母 A/B/C/D
                "answer_text": row[h["answer_text"]], # 正确答案的具体内容
                "source_title": row[h["source_title"]],
            }
        )
    return items


def build_mc_question(item):
    """将选择题拼成完整提问文本（含选项）。"""
    return (
        f"{item['question']}\n"
        f"A. {item['option_a']}\n"
        f"B. {item['option_b']}\n"
        f"C. {item['option_c']}\n"
        f"D. {item['option_d']}"
    )


judge_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


def extract_choice(answer_text: str) -> str:
    """从 RAG 回答中提取选项字母（A/B/C/D）。"""
    if not answer_text:
        return ""
    for ch in ("A", "B", "C", "D"):
        if ch in answer_text[:20]:
            return ch
    return ""


def llm_judge_choice(question: str, options: dict, correct_letter: str, actual_answer: str) -> bool:
    """让 LLM 判断 RAG 的回答是否选了正确选项。"""
    correct_text = options.get(correct_letter, "")
    prompt = (
        f"以下是一道选择题及系统给出的回答，判断系统回答是否选了正确答案。\n"
        f"只回复 YES 或 NO。\n\n"
        f"题目：{question}\n"
        f"正确答案：{correct_letter}. {correct_text}\n"
        f"系统回答：{actual_answer}"
    )
    resp = judge_client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=5,
    )
    content = resp.choices[0].message.content
    if content:
        return content.strip().upper().startswith("YES")
    # 中转 API 偶发返回空 content，退回字母比对，避免整轮评测崩溃
    return extract_choice(actual_answer) == correct_letter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题，用于调试")
    parser.add_argument("--source", choices=["excel", "word", "pdf"], default=None)
    args = parser.parse_args()

    builder = AnswerBuilder()
    items = load_qa_items(source_filter=args.source)
    if args.limit:
        items = items[: args.limit]

    # 断点续传：加载已有进度（同一 id 取最后一次记录）
    recorded: dict = {}
    if PROGRESS_PATH.exists():
        for line in PROGRESS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            recorded[r["id"]] = r
    done_ids = {rid for rid, r in recorded.items() if not r.get("error")}
    if done_ids:
        print(f"[续传] 已完成 {len(done_ids)} 题，跳过；出错的题将重试")

    progress_fp = PROGRESS_PATH.open("a", encoding="utf-8")

    for item in items:
        if item["id"] in done_ids:
            continue
        full_q = build_mc_question(item)
        print(f"[{item['id']}] {item['source_type']}/{item['difficulty']} {item['question'][:40]}...")

        try:
            result = builder.answer(full_q)
            actual = result.get("answer", "")
            refuse = result.get("refuse_reason")

            options = {
                "A": item["option_a"],
                "B": item["option_b"],
                "C": item["option_c"],
                "D": item["option_d"],
            }

            # 先尝试从回答中直接提取选项字母
            extracted = extract_choice(actual)
            if extracted:
                is_correct = extracted == item["answer"]
            else:
                # 回答没有明确选项字母时，用 LLM judge 判断
                is_correct = llm_judge_choice(full_q, options, item["answer"], actual) if actual else False

            record = {
                "id": item["id"],
                "source_type": item["source_type"],
                "difficulty": item["difficulty"],
                "qa_type": item.get("qa_type", "unknown"),
                "question": item["question"][:80],
                "correct_answer": item["answer"],
                "actual_answer": actual[:100] if actual else "",
                "is_correct": is_correct,
                "refused": bool(refuse),
                "latency_ms": result.get("latency_ms"),
            }
        except Exception as e:  # 单题异常不拖垮整轮，记为错误后继续
            print(f"    [出错] {e}")
            record = {
                "id": item["id"],
                "source_type": item["source_type"],
                "difficulty": item["difficulty"],
                "qa_type": item.get("qa_type", "unknown"),
                "question": item["question"][:80],
                "correct_answer": item["answer"],
                "actual_answer": "",
                "is_correct": False,
                "refused": False,
                "latency_ms": None,
                "error": str(e),
            }

        recorded[item["id"]] = record
        progress_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        progress_fp.flush()

    progress_fp.close()

    # 从记录聚合本轮范围内的结果
    results = [recorded[item["id"]] for item in items if item["id"] in recorded]
    total = len(results)
    correct = sum(1 for r in results if r["is_correct"])
    errored = [r["id"] for r in results if r.get("error")]

    by_source: dict[str, dict] = {}
    by_qa_type: dict[str, dict] = {}
    for r in results:
        s = by_source.setdefault(r["source_type"], {"total": 0, "correct": 0})
        s["total"] += 1
        s["correct"] += int(r["is_correct"])
        q = by_qa_type.setdefault(r.get("qa_type", "unknown"), {"total": 0, "correct": 0})
        q["total"] += 1
        q["correct"] += int(r["is_correct"])

    source_summary = {
        src: {
            "total": v["total"],
            "correct": v["correct"],
            "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0,
        }
        for src, v in by_source.items()
    }
    qa_type_summary = {
        qt: {
            "total": v["total"],
            "correct": v["correct"],
            "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0,
        }
        for qt, v in by_qa_type.items()
    }
    report = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0,
        "by_source": source_summary,
        "by_qa_type": qa_type_summary,
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n评测完成：{correct}/{total}，准确率 {report['accuracy']:.1%}")
    for src, v in source_summary.items():
        print(f"  {src}: {v['correct']}/{v['total']} = {v['accuracy']:.1%}")
    print(f"  --- 按题型 ---")
    for qt, v in qa_type_summary.items():
        print(f"  {qt}: {v['correct']}/{v['total']} = {v['accuracy']:.1%}")
    if errored:
        print(f"  [注意] {len(errored)} 题执行出错（已记为错误）：{errored}")
        print(f"         重跑本脚本会自动重试这些题；如需从头跑请先删除 {PROGRESS_PATH}")
    print(f"报告保存至：{REPORT_PATH}")


if __name__ == "__main__":
    main()
