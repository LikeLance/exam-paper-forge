#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 质检器自测（证明 check_exam.py 真能抓到错）

做法：生成一份干净的骨架，再往里面逐个注入典型错误，
      每次都要求 check_exam.py 报出对应规则的 ERROR。
      抓不到就是质检器失灵，比没有质检更危险。

用法：
    python selftest.py
    python selftest.py --keep    # 保留临时目录，便于人工看
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
INIT = HERE / "init_exam.py"
CHECK = HERE / "check_exam.py"


def run_init(dst: Path, preset="engineering"):
    r = subprocess.run([sys.executable, str(INIT), "--preset", preset,
                        "--course", "自测课程", "--out", str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)


def run_check(dst: Path):
    r = subprocess.run([sys.executable, str(CHECK), str(dst), "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(r.stdout), r.returncode
    except json.JSONDecodeError:
        raise RuntimeError("check 输出不是 JSON：\n" + r.stdout + r.stderr)


def errors_for(items, rule):
    return [i for i in items if i["rule"] == rule and i["severity"] == "ERROR"]


def edit(path: Path, fn):
    path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8")


# ---------------- 各测试用例 ----------------

def case_r03(d: Path):
    """删掉 A 卷一个填空线 → 空数少 1"""
    edit(d / "paper_A.tex", lambda t: t.replace(r"\kong[2.2cm]", "", 1))


def case_r04(d: Path):
    """删掉 A 卷第一道单选题的中间选项 B → 选项缺项（删末尾项无法从字母序列看出，不测）"""
    edit(d / "paper_A.tex",
         lambda t: t.replace(r"B. （选项）\qquad ", "", 1))


def case_r05(d: Path):
    """把 A 卷单选第 1 题答案改成 E → 超出实际选项数"""
    edit(d / "ans_A.tex", lambda t: t.replace(r"\thao{1. A}", r"\thao{1. E}", 1))


def case_r06(d: Path):
    """同一道真实题干出现在 A、B 两卷 → 跨卷重复"""
    real = ("\\xiaoti{1. 线性时不变系统的单位冲激响应完全表征其"
            "输入输出关系，这一性质称为\\kong[2.0cm]。}")
    stub = r"\xiaoti{1. （题干）\kong[1.8cm]（题干）\kong[1.4cm]。}"
    for name in ("paper_A.tex", "paper_B.tex"):
        edit(d / name, lambda t, s=stub, r=real: t.replace(s, r, 1))


def case_r09(d: Path):
    """骨架原样 → 应报占位未填"""
    pass


CASES = [
    ("R03", "填空空数与分值不符", case_r03),
    ("R04", "单选选项缺项", case_r04),
    ("R05", "单选答案越界", case_r05),
    ("R06", "A/B 卷题目重复", case_r06),
    ("R09", "骨架占位未填", case_r09),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="exam-selftest-"))
    passed = failed = 0
    print(f"临时目录：{root}\n")

    # 基线：干净骨架只应有 R09 警告，不应有 ERROR
    base = root / "baseline"
    run_init(base)
    items, code = run_check(base)
    errs = [i for i in items if i["severity"] == "ERROR"]
    if errs:
        print("[FAIL] 基线不该有 ERROR：")
        for e in errs:
            print("       ", e["rule"], e["message"])
        failed += 1
    else:
        print("[ ok ] 基线：干净骨架无 ERROR")
        passed += 1

    for rule, desc, fn in CASES:
        d = root / rule
        run_init(d)
        fn(d)
        items, code = run_check(d)
        hit = errors_for(items, rule) if rule != "R09" else [
            i for i in items if i["rule"] == "R09" and i["severity"] == "WARN"]
        if hit:
            print(f"[ ok ] {rule} 抓到了：{desc}")
            print(f"       → {hit[0]['message'][:78]}")
            passed += 1
        else:
            print(f"[FAIL] {rule} 没抓到：{desc}")
            failed += 1

    print(f"\n{passed} 通过 / {failed} 失败")
    if a.keep:
        print(f"保留目录：{root}")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
