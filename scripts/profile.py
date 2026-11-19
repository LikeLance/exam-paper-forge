#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
profile.py —— 考情画像：让出卷权重来自本校真题，而不是模型凭印象分配

学校不同、老师不同，同一门课的侧重点天差地别。这个脚本负责把"侧重点"变成
一份可复用的 profile.json，再由 init/check 强制约束出卷。

四个子命令：

    # 1. 从教材目录生成章节骨架
    python profile.py from-outline outline.txt --course "机电传动控制" --out profile.json

    # 2. 从往年卷反推各章分值（tex / txt / md，多个文件一起传）
    python profile.py from-papers "2023A卷.tex" "2024B卷.tex" --profile profile.json

    # 3. 校验（分值是否配平、关键词是否重复）
    python profile.py check profile.json

    # 4. 看当前画像
    python profile.py show profile.json

没有往年卷时，用 init 建一份按通用章节的骨架，把老师划的重点手动填进 note 和 points。

判定规则：一道题命中某章关键词最多，就归该章；一个都没命中的进"未分类"，
这些题要人工看一眼——通常是新考点，或者是停考的老内容。
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------- 解析往年卷 ----------------

def strip_comments(t: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", t)


def braced(text: str, brace_pos: int) -> int:
    """text[brace_pos] == '{'，返回与其配对的 '}' 下标；用于处理任意层嵌套"""
    depth = 0
    for j in range(brace_pos, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def extract_cmd(text: str, cmd: str):
    """抽出 \\cmd{...} 的全部内容，支持 \\cmd{...}{...} 取第一个参数。
    正则处理不了 $\\dfrac{a}{b}$ 这种两层嵌套，会静默漏题，所以用括号计数。"""
    out, i, tag = [], 0, "\\" + cmd
    while True:
        k = text.find(tag, i)
        if k < 0:
            break
        b = k + len(tag)
        while b < len(text) and text[b] in " \t":
            b += 1
        if b >= len(text) or text[b] != "{":
            i = k + len(tag)
            continue
        e = braced(text, b)
        if e < 0:
            break
        out.append(text[b + 1:e])
        i = e + 1
    return out


def parse_tex(path: Path):
    """返回 [(题干, 分值)]，分值按题干里的（N 分）或大题均分推算"""
    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    heads = [m.start() for m in re.finditer(r"\\dati(?![A-Za-z])", text)]
    items = []
    for idx, pos in enumerate(heads):
        body = text[pos: heads[idx + 1] if idx + 1 < len(heads) else len(text)]
        m = re.search(r"共\s*(\d+(?:\.\d+)?)\s*分", body[:220])
        total = float(m.group(1)) if m else None
        stems = extract_cmd(body, "xiaoti")
        if not stems:
            continue
        per = (total / len(stems)) if total else 2.0
        for s in stems:
            pm = re.search(r"（\s*(\d+(?:\.\d+)?)\s*分\s*）", s)
            items.append((re.sub(r"\\[a-zA-Z]+", " ", s), float(pm.group(1)) if pm else per))
    return items


def parse_plain(path: Path):
    """txt / md：题目以「1. 」「1、」「（1）」起行，分值取题干里的（N 分）"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    total_m = re.search(r"满分\s*[:：]?\s*(\d+)\s*分", text)
    grand = float(total_m.group(1)) if total_m else 100.0

    items, buf = [], None
    for l in lines:
        if re.match(r"^[(（]?\d{1,2}[)）.、．]", l):
            if buf:
                items.append(buf)
            buf = l
        elif buf is not None:
            buf += " " + l
    if buf:
        items.append(buf)

    if not items:
        return []
    per = grand / len(items)
    out = []
    for s in items:
        pm = re.search(r"（\s*(\d+(?:\.\d+)?)\s*分\s*）", s)
        out.append((s, float(pm.group(1)) if pm else per))
    return out


def load_paper(path: Path):
    p = path.expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"文件不存在：{p}")
    if p.suffix.lower() == ".tex":
        return parse_tex(p)
    if p.suffix.lower() in (".txt", ".md", ".markdown"):
        return parse_plain(p)
    raise SystemExit(f"不支持 {p.suffix}，请先转成 txt（PDF 可用 pdftotext -layout 转）")


# ---------------- 归章 ----------------

def build_weights(chapters) -> dict:
    """关键词区分度：只出现在一章的词权重 2，跨章共用词权重 1。
    避免"电动机"这类通用词把题目都吸到同一章。"""
    cnt = {}
    for ch in chapters:
        for kw in ch.get("keywords", []):
            cnt[kw] = cnt.get(kw, 0) + 1
    return {kw: (2.0 if c == 1 else 1.0) for kw, c in cnt.items()}


def classify(stem: str, chapters, weights=None) -> str | None:
    """命中分 = Σ(关键词长度 × 区分度)，长词更具体，得分更高"""
    weights = weights or build_weights(chapters)
    best, best_s = None, 0.0
    for ch in chapters:
        s = sum(len(kw) * weights.get(kw, 1.0)
                for kw in ch.get("keywords", []) if kw and kw in stem)
        if s > best_s:
            best, best_s = ch["id"], s
    return best


def largest_remainder(values: dict, total: int) -> dict:
    """把浮点比例还原成整数且合计等于 total"""
    s = sum(values.values())
    if s <= 0:
        return {k: 0 for k in values}
    raw = {k: v * total / s for k, v in values.items()}
    floor = {k: int(math.floor(v)) for k, v in raw.items()}
    rest = total - sum(floor.values())
    order = sorted(raw, key=lambda k: raw[k] - floor[k], reverse=True)
    for k in order[:rest]:
        floor[k] += 1
    return floor


# ---------------- 子命令 ----------------

def cmd_from_outline(a):
    txt = Path(a.outline).expanduser().read_text(encoding="utf-8", errors="replace")
    chapters = []
    for i, line in enumerate([l.strip() for l in txt.splitlines() if l.strip()], 1):
        # 去掉"第1章 "前缀，保留章名
        name = re.sub(r"^第\s*[0-9一二三四五六七八九十]+\s*章[\s、.．:：]*", "", line)
        chapters.append({
            "id": f"ch{i}", "name": name or line, "points": 0, "level": "理解",
            "must": False, "keywords": [], "note": ""
        })
    _rebalance(chapters, a.points)
    prof = _blank_profile(a.course, chapters, a.points)
    _dump(prof, Path(a.out))
    print(f"已生成 {a.out}：{len(chapters)} 章，分值暂按均值分配（共 {a.points} 分）")
    print("下一步：给每章填 keywords（3–8 个考点词），再跑 from-papers 从真题反推分值")


def cmd_init(a):
    chapters = []
    for i in range(1, a.chapters + 1):
        chapters.append({
            "id": f"ch{i}", "name": f"第 {i} 章", "points": 0, "level": "理解",
            "must": False, "keywords": [], "note": ""
        })
    _rebalance(chapters, a.points)
    prof = _blank_profile(a.course, chapters, a.points)
    _dump(prof, Path(a.out))
    print(f"已生成 {a.out}：{a.chapters} 章占位，请改章名、填 keywords、调 points")


def _blank_profile(course, chapters, total):
    return {
        "course": course, "school": "", "major": "", "term": "",
        "total": total, "chapters": chapters,
        "question_mix": {"fill": 15, "choice": 20, "tf": 10, "short": 20, "calc": 25, "design": 10},
        "style_notes": [], "sources": [], "excluded": [],
    }


def _rebalance(chapters, total):
    n = len(chapters)
    base = total // n
    for i, ch in enumerate(chapters):
        ch["points"] = base if i < n - 1 else total - base * (n - 1)


def cmd_from_papers(a):
    prof_p = Path(a.profile).expanduser().resolve()
    prof = json.loads(prof_p.read_text(encoding="utf-8"))
    chapters = prof["chapters"]
    if not any(ch.get("keywords") for ch in chapters):
        raise SystemExit("profile 里所有章节都没有 keywords，无法匹配。先给每章填 3–8 个考点词。")

    per_ch, cnt, unmatched, unmatched_pts = {}, {}, [], 0.0
    total_pts = 0.0
    weights = build_weights(chapters)
    for f in a.papers:
        items = load_paper(Path(f))
        print(f"  {Path(f).name}: {len(items)} 题")
        for stem, pts in items:
            total_pts += pts
            cid = classify(stem, chapters, weights)
            if cid is None:
                unmatched.append((stem, pts))
                unmatched_pts += pts
                continue
            per_ch[cid] = per_ch.get(cid, 0.0) + pts
            cnt[cid] = cnt.get(cid, 0) + 1

    if total_pts <= 0:
        raise SystemExit("没解析出任何分值，检查往年卷格式")

    others = {"__unmatched__": unmatched_pts} if unmatched_pts else {}
    alloc = largest_remainder({**per_ch, **others}, prof["total"])

    print(f"\n{'章节':<6}{'名称':<28}{'旧分值':>7}{'新分值':>7}{'题数':>6}")
    print("-" * 60)
    for ch in chapters:
        old = ch["points"]
        new = alloc.get(ch["id"], 0)
        print(f"{ch['id']:<6}{ch['name'][:26]:<28}{old:>7}{new:>7}{cnt.get(ch['id'], 0):>6}")
        ch["points"] = new
    if unmatched:
        print(f"{'—':<6}{'未分类（需人工确认）':<28}{'':>7}{alloc.get('__unmatched__', 0):>7}{len(unmatched):>6}")
        if a.show_unmatched:
            print("\n未分类样本（看这些题漏了哪些关键词）：")
            for stem, pts in unmatched[:a.show_unmatched]:
                s = re.sub(r"\s+", " ", stem).strip()
                print(f"  [{pts:.0f} 分] {s[:56]}")

    if a.dry:
        print("\n[dry-run] 未写入文件")
        return
    prof_p.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写回 {prof_p}")
    if unmatched:
        print(f"注意：{len(unmatched)} 题（{unmatched_pts:.0f} 分）没匹配到任何章节，"
              f"多半是新考点或关键词没覆盖，建议补 keywords 后重跑")


def cmd_check(a):
    p = Path(a.profile).expanduser().resolve()
    prof = json.loads(p.read_text(encoding="utf-8"))
    errs, warns = [], []

    chs = prof.get("chapters", [])
    if not chs:
        errs.append("没有 chapters")
    ids = [c["id"] for c in chs]
    if len(set(ids)) != len(ids):
        errs.append("章节 id 重复")
    s = sum(c.get("points", 0) for c in chs)
    if s != prof.get("total", 100):
        errs.append(f"章节分值合计 {s} ≠ total {prof.get('total', 100)}")

    kw_owner = {}
    for c in chs:
        if not c.get("keywords"):
            warns.append(f"{c['id']}「{c['name']}」没有 keywords，往年卷里命中不了这一章")
        for kw in c.get("keywords", []):
            if kw in kw_owner and kw_owner[kw] != c["id"]:
                warns.append(f"关键词「{kw}」同时出现在 {kw_owner[kw]} 与 {c['id']}，匹配会偏向先出现的")
            kw_owner.setdefault(kw, c["id"])
        if c.get("points", 0) == 0:
            warns.append(f"{c['id']}「{c['name']}」分值为 0，确认是不考还是漏填")

    must = [c for c in chs if c.get("must") and c.get("points", 0) == 0]
    if must:
        errs.append("标记必考的章节分值为 0：" + "、".join(c["id"] for c in must))

    mix = prof.get("question_mix", {})
    if mix and sum(mix.values()) != prof.get("total", 100):
        warns.append(f"question_mix 合计 {sum(mix.values())} ≠ total")

    for e in errs:
        print(f"[  X  ] {e}")
    for w in warns:
        print(f"[ !!! ] {w}")
    if not errs and not warns:
        print("[  ok ] 画像完整，分值配平")
    print()
    print(f"章节 {len(chs)} 个，合计 {s} 分，必考 {sum(1 for c in chs if c.get('must'))} 章")
    return 1 if errs else 0


def cmd_show(a):
    prof = json.loads(Path(a.profile).expanduser().read_text(encoding="utf-8"))
    print(f"{prof.get('course','?')} ｜ {prof.get('school','（未填学校）')} ｜ 满分 {prof.get('total',100)}")
    print(f"{'章节':<6}{'名称':<30}{'分值':>5}{'占比':>7}{'必考':>5}  关键词")
    print("-" * 96)
    for c in prof["chapters"]:
        pct = c["points"] / prof.get("total", 100) * 100
        kw = "、".join(c.get("keywords", [])[:4])
        print(f"{c['id']:<6}{c['name'][:28]:<30}{c['points']:>5}{pct:>6.0f}%{'√' if c.get('must') else '':>5}  {kw}")
    if prof.get("style_notes"):
        print("\n命题习惯：")
        for s in prof["style_notes"]:
            print("  - " + s)
    if prof.get("excluded"):
        print("\n明确不考：" + "、".join(prof["excluded"]))


def _dump(obj, path: Path):
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="考情画像：把本校侧重点变成可执行的出卷约束")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("init", help="建空白画像")
    p1.add_argument("--course", required=True)
    p1.add_argument("--chapters", type=int, default=8)
    p1.add_argument("--points", type=int, default=100)
    p1.add_argument("--out", required=True)
    p1.set_defaults(func=cmd_init)

    p2 = sub.add_parser("from-outline", help="从教材目录文本生成章节")
    p2.add_argument("outline")
    p2.add_argument("--course", required=True)
    p2.add_argument("--points", type=int, default=100)
    p2.add_argument("--out", required=True)
    p2.set_defaults(func=cmd_from_outline)

    p3 = sub.add_parser("from-papers", help="从往年卷反推各章分值")
    p3.add_argument("papers", nargs="+")
    p3.add_argument("--profile", required=True)
    p3.add_argument("--dry", action="store_true", help="只打印不写回")
    p3.add_argument("--show-unmatched", type=int, default=8,
                    help="打印前 N 条未归章的题目，便于补关键词（0 关闭）")
    p3.set_defaults(func=cmd_from_papers)

    p4 = sub.add_parser("check", help="校验画像")
    p4.add_argument("profile")
    p4.set_defaults(func=cmd_check)

    p5 = sub.add_parser("show", help="查看画像")
    p5.add_argument("profile")
    p5.set_defaults(func=cmd_show)

    a = ap.parse_args()
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
