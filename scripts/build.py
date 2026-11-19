#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py —— 一键编译期末模拟卷（xelatex 三遍 + 编译后自检）

用法：
    python build.py <exam_dir>              # 编译试卷册与答案册
    python build.py <exam_dir> --paper      # 只编译试卷册
    python build.py <exam_dir> --ans        # 只编译答案册
    python build.py <exam_dir> --clean      # 先清掉中间文件

为什么是三遍：第一遍写 .aux，第二遍解 "共 N 页" 与交叉引用，第三遍才稳定。
只跑一遍会得到 "共 ?? 页"，这是最常见的交付事故。
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_xelatex(tex: Path, times: int = 3) -> tuple[bool, str]:
    log_tail = ""
    for i in range(times):
        proc = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
            cwd=str(tex.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            log_tail = proc.stdout[-4000:]
            return False, log_tail
    log = tex.with_suffix(".log")
    if log.exists():
        log_tail = log.read_text(encoding="utf-8", errors="replace")
    return True, log_tail


def summarize(log: str) -> dict:
    pages = re.search(r"Output written on .*?\((\d+) pages?", log)
    overfull = len(re.findall(r"Overfull \\hbox", log))
    underfull = len(re.findall(r"Underfull \\hbox", log))
    err = re.findall(r"^! (.+)$", log, re.M)
    missing = re.findall(r"LaTeX Warning: Reference .*? undefined", log)
    return {
        "pages": int(pages.group(1)) if pages else 0,
        "overfull": overfull,
        "underfull": underfull,
        "errors": err,
        "undefined_refs": len(missing),
    }


def main():
    ap = argparse.ArgumentParser(description="编译期末模拟卷")
    ap.add_argument("exam_dir")
    ap.add_argument("--paper", action="store_true", help="只编译试卷册")
    ap.add_argument("--ans", action="store_true", help="只编译答案册")
    ap.add_argument("--clean", action="store_true", help="编译前清理 aux/log/out")
    ap.add_argument("--times", type=int, default=3)
    a = ap.parse_args()

    d = Path(a.exam_dir).expanduser().resolve()
    if not d.is_dir():
        print(f"目录不存在：{d}")
        return 1
    if not shutil.which("xelatex"):
        print("找不到 xelatex，请确认 TeX Live / MiKTeX 已装且加入 PATH")
        return 1

    targets = []
    if not a.ans:
        targets.append(d / "main_paper.tex")
    if not a.paper:
        targets.append(d / "main_ans.tex")

    if a.clean:
        for pat in ("*.aux", "*.log", "*.out", "*.toc"):
            for f in d.glob(pat):
                f.unlink(missing_ok=True)

    failed = 0
    for tex in targets:
        if not tex.exists():
            print(f"跳过：{tex.name} 不存在")
            continue
        print(f"编译 {tex.name} ...", end=" ", flush=True)
        ok, log = run_xelatex(tex, a.times)
        if not ok:
            print("失败")
            print(log[-2500:])
            failed += 1
            continue
        s = summarize(log)
        flag = ""
        if s["overfull"] > 0:
            flag += f"，排版溢出 {s['overfull']} 处"
        if s["undefined_refs"]:
            flag += f"，未定义引用 {s['undefined_refs']} 处"
        print(f"OK  {s['pages']} 页{flag}")

    pdfs = sorted(d.glob("main_*.pdf"))
    if pdfs:
        print("\n产物：")
        for p in pdfs:
            print(f"  {p}  ({p.stat().st_size / 1024:.0f} KB)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
