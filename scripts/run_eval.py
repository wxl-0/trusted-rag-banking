#!/usr/bin/env python
"""
对评测集跑问答，输出 eval_report.json。
用法：python scripts/run_eval.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI
from dotenv import load_dotenv
from src.generator.answer_builder import AnswerBuilder

load_dotenv()

QA_PATH = Path("data/eval/qa_seed.jsonl")
REPORT_PATH = Path("data/eval/eval_report.json")

judge_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


def llm_judge(question: str, expected: str, actual: str) -> bool:
    prompt = f"""判断以下答案是否与标准答案意思相符（关键数字和事实必须一致）。
只回复 YES 或 NO。

问题：{question}
标准答案：{expected}
实际答案：{actual}"""
    resp = judge_client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0, max_tokens=5,
    )
    return resp.choices[0].message.content.strip().upper() == "YES"


def main():
    builder = AnswerBuilder()
    qa_items = []
    with open(QA_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                qa_items.append(json.loads(line))

    results = []
    correct = 0

    for item in qa_items:
        print(f"[评测] {item['id']}: {item['question'][:30]}...")
        result = builder.answer(item["question"])
        actual_answer = result.get("answer", "")
        is_correct = llm_judge(item["question"], item["answer"], actual_answer) if actual_answer else False
        if is_correct:
            correct += 1
        results.append({
            "id": item["id"],
            "question": item["question"],
            "expected": item["answer"],
            "actual": actual_answer,
            "correct": is_correct,
            "confidence": result.get("confidence"),
            "refuse_reason": result.get("refuse_reason"),
            "latency_ms": result.get("latency_ms"),
        })

    total = len(qa_items)
    report = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0,
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n评测完成：{correct}/{total}，准确率 {report['accuracy']:.1%}")
    print(f"报告保存至：{REPORT_PATH}")


if __name__ == "__main__":
    main()
