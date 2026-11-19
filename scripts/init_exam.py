#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_exam.py —— 为任意学校、任意课程生成期末模拟卷工程骨架

按学科选预设，一条命令出全套骨架（题数、空数、答题区高度都算好）：

    python init_exam.py --preset engineering --course "机电传动控制" --school "××大学" --out ./机电传动
    python init_exam.py --preset humanities  --course "马克思主义基本原理" --out ./马原
    python init_exam.py --preset medical     --course "内科学" --out ./内科学
    python init_exam.py --list              # 查看全部预设

预设只决定"题型配比与分值结构"，版式全部通用；
要改分值传 --scores，要改套数传 --papers。
"""

import argparse
import copy
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASSETS = Path(__file__).resolve().parent.parent / "assets"
CN_NUM = "一二三四五六七八九十"


DEFAULT_NOTICE = (r"1. 答案一律写在试卷相应位置，写在草稿纸上无效；"
                  r"2. 计算题须写出主要公式与演算过程，只有结果不给分；"
                  r"3. 答卷前请将密封线内项目填写清楚。")

# 试卷说明按学科改写：文科卷不该出现"计算题须写出公式"，医学卷要强调填涂规则
PRESET_NOTICE = {
    "engineering": DEFAULT_NOTICE,
    "science": DEFAULT_NOTICE,
    "cs": (r"1. 答案一律写在试卷相应位置，写在草稿纸上无效；"
           r"2. 程序题须给出完整可运行代码，只写伪代码不给满分；"
           r"3. 代码缩进一律用空格，答题前请填写密封线内项目。"),
    "humanities": (r"1. 答案写在答题纸上，写在试题册上无效；"
                   r"2. 论述题要求观点明确、层次清晰、理论联系实际；"
                   r"3. 答题前请将密封线内项目填写清楚。"),
    "law": (r"1. 答案写在答题纸上，写在试题册上无效；"
            r"2. 案例分析须按“结论—法律依据—理由”三段式作答；"
            r"3. 只写结论不写依据的不得满分。"),
    "medical": (r"1. 答案填涂在答题卡上，写在试题册上无效；"
                r"2. 多项选择题多选、少选、错选均不得分；"
                r"3. 病例分析题须写出诊断、诊断依据、鉴别诊断与处理原则。"),
    "language": (r"1. 答案写在答题卡上，写在试题册上无效；"
                 r"2. 翻译题要求译文通顺、忠实原文；"
                 r"3. 写作题须写在指定区域内，超出部分不计分。"),
    "business": DEFAULT_NOTICE,
}


# 评分说明按学科改写：文科卷不该出现"填空题按空给分"
GRADE_DEFAULT = (r"填空题按空给分，答案正确即得分；选择题、判断题不倒扣分；"
                 r"简答题按要点给分，答出关键术语与结论即可，表述完整、条理清楚者可在该题分值内适当调整；"
                 r"计算题按步骤给分，公式正确而结果错误的扣 1～2 分，只有结果无过程的不得分。")

PRESET_GRADE = {
    "engineering": GRADE_DEFAULT,
    "science": GRADE_DEFAULT,
    "business": GRADE_DEFAULT,
    "cs": (r"选择题、填空题按空/题给分，不倒扣；简答题按要点给分；"
           r"程序阅读题结果正确但复杂度分析错误扣一半；"
           r"算法设计题按思路正确性、边界处理、代码规范分档给分，能运行但有边界缺陷的不给满分。"),
    "humanities": (r"名词解释按定义与关键要素给分；"
                   r"简答题按要点给分，答出核心术语与结论即可；"
                   r"论述题按“观点—论证—结论”分层给分，观点正确、层次清晰、联系实际者可在该题分值内上浮 1～2 分；"
                   r"材料分析题须结合材料作答，脱离材料空谈理论的酌情扣分。"),
    "law": (r"选择题、判断题不倒扣；简答题按要点给分；"
            r"法条分析题须写明构成要件与法律后果，缺一扣半；"
            r"案例分析题按“结论—法律依据—理由”三段给分，结论错则依据与理由部分不计分。"),
    "medical": (r"选择题按题给分，多选、少选、错选均不得分；"
                r"名词解释按关键要素给分；简答题按要点给分；"
                r"病例分析题按“诊断—诊断依据—鉴别诊断—处理原则”四段给分，诊断错误者该题不超过 1/3 分。"),
    "language": (r"客观题按题给分，不倒扣；"
                 r"翻译题按忠实与通顺两方面各占一半给分；"
                 r"写作题按内容、结构、语言三项分档给分，字数不足按比例扣分。"),
}


def S(kind, title, points, per=0, n=1, blank=4.2, extra="", opts=4):
    return dict(kind=kind, title=title, points=points, per=per, n=n,
                blank=blank, extra=extra, opts=opts)


# ============================================================
#  学科预设：题型配比不同，版式完全相同
#  分值合计均为 100，可按需用 --scores 覆盖
# ============================================================
PRESETS = {
    "engineering": dict(
        label="工科·机电类（机械/电气/自动化/车辆）",
        hint="计算与设计并重，允许画图；计算题分步设问便于按步给分",
        plan=[
            S("fill", "填空题", 15, 1, 15, blank=6.0),
            S("choice", "单项选择题", 20, 2, 10),
            S("tf", "判断题", 10, 1, 10),
            S("short", "简答题", 20, 5, 4, blank=4.2),
            S("calc", "计算题", 25, 0, 3, blank=9.0),
            S("design", "设计题", 10, 0, 1, blank=15.0),
        ]),
    "science": dict(
        label="理科·数学/物理/电路/信号",
        hint="推导与证明占比高，答案区要够写完整推导过程",
        plan=[
            S("fill", "填空题", 20, 2, 10, blank=5.0),
            S("choice", "单项选择题", 16, 2, 8),
            S("calc", "计算题", 44, 0, 4, blank=11.0),
            S("prove", "证明题", 20, 0, 2, blank=10.0),
        ]),
    "cs": dict(
        label="计算机·数据结构/操作系统/网络",
        hint="程序阅读与算法设计并重，代码块用 code 环境，注意等宽字体",
        plan=[
            S("choice", "单项选择题", 30, 2, 15),
            S("fill", "填空题", 10, 1, 10, blank=4.0),
            S("short", "简答题", 20, 5, 4, blank=4.5),
            S("code_read", "程序阅读题", 15, 5, 3, blank=5.0),
            S("code_write", "算法设计题", 25, 0, 1, blank=14.0),
        ]),
    "humanities": dict(
        label="人文社科·思政/文学/历史/教育",
        hint="论述题与材料分析题答题量大，空白区按手写字数估：一行约 28 字，1cm ≈ 1.6 行",
        plan=[
            S("term", "名词解释", 20, 5, 4, blank=2.6),
            S("short", "简答题", 32, 8, 4, blank=4.4, extra="要求观点明确、条理清晰"),
            S("essay", "论述题", 30, 15, 2, blank=9.5, extra="要求结合理论与实际展开论述"),
            S("material", "材料分析题", 18, 0, 1, blank=12.0, extra="阅读所给材料后回答问题"),
        ]),
    "law": dict(
        label="法学·各部门法",
        hint="以法条与案例为核心，答案要给「结论—依据—分析」三段式",
        plan=[
            S("choice", "单项选择题", 30, 2, 15),
            S("tf", "判断题", 10, 1, 10),
            S("short", "简答题", 18, 6, 3, blank=6.0),
            S("law", "法条分析题", 22, 11, 2, blank=10.0),
            S("case", "案例分析题", 20, 0, 1, blank=14.0),
        ]),
    "medical": dict(
        label="医学·基础与临床",
        hint="多选题五个选项（A–E）；病例分析按「诊断—依据—鉴别—处理」给分",
        plan=[
            S("choice", "单项选择题", 20, 1, 20, opts=5),
            S("multi", "多项选择题", 20, 2, 10, opts=5),
            S("term", "名词解释", 16, 4, 4, blank=2.6),
            S("short", "简答题", 24, 6, 4, blank=5.5),
            S("case", "病例分析题", 20, 0, 1, blank=14.0),
        ]),
    "language": dict(
        label="语言·大学英语/语文",
        hint="客观题靠题量，主观题（翻译/写作）留足书写空间；写作题标注字数要求",
        plan=[
            S("choice", "单项选择题", 20, 1, 20),
            S("fill", "完形填空", 10, 1, 10, blank=4.0),
            S("reading", "阅读理解", 20, 5, 4, blank=8.0),
            S("translate", "翻译题", 20, 10, 2, blank=7.0),
            S("writing", "写作题", 30, 0, 1, blank=18.0, extra="不少于 200 字"),
        ]),
    "business": dict(
        label="经管·经济学/管理学/会计",
        hint="计算与案例并重；案例题按「理论—分析—结论」给分",
        plan=[
            S("choice", "单项选择题", 30, 2, 15),
            S("tf", "判断题", 10, 1, 10),
            S("short", "简答题", 20, 5, 4, blank=5.0),
            S("calc", "计算题", 20, 10, 2, blank=9.0),
            S("case", "案例分析题", 20, 0, 1, blank=14.0),
        ]),
}

KIND_HINT = {
    "fill": "本大题共 {n} 个空；每空用 \\kong[宽度]，宽度按答案长度给 1.2–2.8cm",
    "choice": "四个选项用 A. …\\qquad B. … 排开；五个选项时两行排布",
    "multi": "多项选择题错选、多选、少选均不得分，卷面要写明这条规则",
    "tf": "陈述句必须能明确判真假，避开“一般”“都”“一定”这类模糊表述",
    "term": "名词解释答案 40–80 字，抓定义 + 要素 + 一句作用",
    "short": "答案 4–6 个要点，每点可独立给分",
    "essay": "答案按「论点—论据—结论」分层，每层单独给分",
    "calc": "分步设问（1）（2）（3），前问结论供后问使用，便于按步给分",
    "prove": "证明题必须给出已知、求证、证明三段，缺“求证”按不规范扣分",
    "code_read": "给一段可运行代码问输出或复杂度；代码用 code 环境，缩进用空格不用 Tab",
    "code_write": "算法设计题给函数签名与约束（数据规模、时空复杂度要求）",
    "design": "给出完整工艺条件，答题区留足画图空间",
    "case": "案例材料 150–300 字，设问 3 小问，逐问给分",
    "material": "材料 200–400 字，设问与材料逐条对应，避免答非所问",
    "law": "法条分析题给出条文原文，问构成要件与适用后果",
    "reading": "每篇材料配 2 小问，一问细节一问主旨",
    "translate": "给出待译段落，注明直译与意译的评分侧重",
    "writing": "写作题给题目或话题 + 字数下限 + 分值构成（内容/结构/语言）",
}


def make_note(s):
    k, p, per = s["kind"], s["points"], s["per"]
    if k == "fill":
        base = f"每空 {per} 分，共 {p} 分"
    elif k in ("choice", "multi", "tf", "term", "short", "essay", "reading", "translate"):
        base = f"每小题 {per} 分，共 {p} 分"
    elif k == "write":
        base = f"共 {p} 分"
    else:
        base = f"共 {p} 分"
    extra = s.get("extra") or ""
    if k == "choice":
        base += "，将正确答案的字母填在括号内"
    elif k == "multi":
        base += "，多选、少选、错选均不得分"
    elif k == "tf":
        base += "，正确的画“√”，错误的画“×”"
    return f"{base}，{extra}" if extra else base


def build_plan(preset: str, scores: str | None) -> list[dict]:
    if preset not in PRESETS:
        raise SystemExit(f"未知预设 {preset}，可选：{', '.join(PRESETS)}")
    plan = copy.deepcopy(PRESETS[preset]["plan"])
    if scores:
        vals = [int(x) for x in re.split(r"[,\s]+", scores.strip()) if x]
        if len(vals) != len(plan):
            raise SystemExit(f"该预设共 {len(plan)} 个大题，--scores 需要 {len(plan)} 个数值")
        for s, p in zip(plan, vals):
            s["points"] = p
        for s in plan:
            if s["per"]:
                if s["points"] % s["per"]:
                    raise SystemExit(f"「{s['title']}」{s['points']} 分无法被每题 {s['per']} 分整除")
                s["n"] = s["points"] // s["per"]
    total = sum(s["points"] for s in plan)
    if total != 100:
        raise SystemExit(f"分值合计 {total} ≠ 100，请调整 --scores")
    for s in plan:
        if s["per"] and s["n"] * s["per"] != s["points"]:
            raise SystemExit(f"「{s['title']}」{s['n']} 题 × {s['per']} 分 ≠ {s['points']} 分")
    return plan


# ============================================================
#  渲染：试卷
# ============================================================
def letters(n):
    return [chr(ord("A") + i) for i in range(n)]


def paper_section(s):
    k = s["kind"]
    note = make_note(s)
    out = [f"\\dati{{{s['title']}}}{{{note}}}",
           f"% 命题提示：{KIND_HINT[k].format(n=s['n'])}", ""]

    if k == "fill":
        # s["n"] 是"空数"而不是"题数"：一道题可含 1–2 个空，空数必须精确
        blanks, i = s["n"], 0
        while blanks > 0:
            i += 1
            if blanks >= 2:
                out += [f"\\xiaoti{{{i}. （题干）\\kong[1.8cm]（题干）\\kong[1.4cm]。}}", ""]
                blanks -= 2
            else:
                out += [f"\\xiaoti{{{i}. （题干）\\kong[2.2cm]。}}", ""]
                blanks -= 1
    elif k in ("choice", "multi"):
        opts = letters(s["opts"])
        per_line = 4 if s["opts"] <= 4 else 5
        for i in range(1, s["n"] + 1):
            block = f"\\xiaoti{{{i}. （题干）（\\hspace{{1.2cm}}）\\\\"
            for j in range(0, len(opts), per_line):
                chunk = opts[j:j + per_line]
                block += "\n" + "\\qquad ".join(f"{c}. （选项）" for c in chunk)
                if j + per_line < len(opts):
                    block += "\\\\"
            block += "}"
            out += [block, ""]
    elif k == "tf":
        for i in range(1, s["n"] + 1):
            out += [f"\\xiaoti{{{i}. （陈述句）。（\\hspace{{1.0cm}}）}}", ""]
    elif k == "code_read":
        for i in range(1, s["n"] + 1):
            out += ["\\begin{ti}",
                    f"\\xiaoti{{{i}.（{s['per']} 分）（题干：阅读下列程序，写出运行结果并说明时间复杂度）}}",
                    "\\begin{code}", "// 待替换为真实代码", "\\end{code}",
                    f"\\kongbai{{{s['blank']}cm}}", "\\end{ti}", ""]
    elif k == "calc":
        per = s["points"] // s["n"]
        for i in range(1, s["n"] + 1):
            pts = per if i < s["n"] else s["points"] - per * (s["n"] - 1)
            out += ["\\begin{ti}",
                    f"\\xiaoti{{{i}.（{pts} 分）（已知条件…）试求：\\\\",
                    "（1）…；\\quad（2）…；\\quad（3）…。}",
                    f"\\kongbai{{{s['blank']}cm}}", "\\end{ti}", ""]
    else:
        # term / short / essay / prove / design / case / material / law / reading / translate / writing
        per = s["per"] or s["points"] // max(s["n"], 1)
        for i in range(1, s["n"] + 1):
            pts = per if i < s["n"] else s["points"] - per * (s["n"] - 1)
            body = f"\\xiaoti{{{i}.（{pts} 分）（题目）}}"
            if k == "prove":
                body = f"\\xiaoti{{{i}.（{pts} 分）（题干：已知…，求证…）}}"
            elif k == "case":
                body = (f"\\xiaoti{{{i}.（{pts} 分）（案例材料，150–300 字）\\\\"
                        "请回答：（1）…；（2）…；（3）…。}")
            elif k == "material":
                body = (f"\\xiaoti{{{i}.（{pts} 分）（材料，200–400 字）\\\\"
                        "结合材料回答：（1）…；（2）…。}")
            elif k == "writing":
                body = f"\\xiaoti{{{i}.（{pts} 分）（题干：作文题目，{s['extra'] or '不少于 200 字'}）}}"
            out += ["\\begin{ti}", body, f"\\kongbai{{{s['blank']}cm}}", "\\end{ti}", ""]
    return "\n".join(out)


# ============================================================
#  渲染：答案册
# ============================================================
def ans_section(s):
    k = s["kind"]
    note = make_note(s)
    out = [f"\\datiA{{{s['title']}（{note}）}}", ""]

    if k == "fill":
        out.append("\\fillhead")
        row = []
        for i in range(1, s["n"] + 1):
            row.append(f"{i}. （答案）")
            if len(row) == 3 or i == s["n"]:
                out.append(" & ".join(row) + " \\\\")
                row = []
        out += ["\\filltail", "",
                f"\\pingfen{{每空 {s['per']} 分，答案含义正确即可给分。}}", ""]
    elif k in ("choice", "multi", "tf"):
        n = s["n"]
        # 20 题就是 21 列，默认 6pt 列距会顶破版心，按题数收紧
        sep = 3.2 if n > 16 else (4.0 if n > 12 else 6.0)
        out += ["\\begin{center}\\zihao{5}",
                f"\\setlength{{\\tabcolsep}}{{{sep}pt}}",
                "\\begin{tabular}{|c|" + "c|" * n + "}", "\\hline",
                "题号 & " + " & ".join(str(i) for i in range(1, n + 1)) + " \\\\ \\hline"]
        ph = "A" if k == "choice" else ("AB" if k == "multi" else "$\\surd$")
        out += ["答案 & " + " & ".join(ph for _ in range(n)) + " \\\\ \\hline",
                "\\end{tabular}", "\\end{center}", ""]
        for i in range(1, n + 1):
            a = "A" if k == "choice" else ("AB" if k == "multi" else "$\\surd$")
            out += [f"\\thao{{{i}. {a}}}\\pingfen{{{s['per']} 分}} （解析：正确项理由；干扰项错在哪）", ""]
    else:
        per = s["per"] or s["points"] // max(s["n"], 1)
        for i in range(1, s["n"] + 1):
            pts = per if i < s["n"] else s["points"] - per * (s["n"] - 1)
            half = max(1, pts // 2)
            rest = max(1, pts - half)
            out += [f"\\thao{{{i}.}}\\yaodian",
                    "\\begin{enumerate}[label=(\\arabic*),leftmargin=2.2em,itemsep=2pt,topsep=2pt]",
                    f"\\item （要点一：核心结论/定义）\\pingfen{{{half} 分}}",
                    f"\\item （要点二：展开/依据/计算过程）\\pingfen{{{rest} 分}}",
                    "\\end{enumerate}", ""]
    return "\n".join(out)


# ============================================================
def main():
    ap = argparse.ArgumentParser(description="生成期末模拟卷工程骨架（任意学校、任意学科）")
    ap.add_argument("--list", action="store_true", help="列出全部学科预设")
    ap.add_argument("--preset", default="engineering", help="学科预设，默认 engineering")
    ap.add_argument("--course", help="课程名，如 信号与系统")
    ap.add_argument("--school", default="××大学")
    ap.add_argument("--college", default="", help="学院名，可留空")
    ap.add_argument("--term", default="2026—2027 学年\\quad 第 1 学期")
    ap.add_argument("--majors", default="", help="适用专业，留空则不打印该行")
    ap.add_argument("--form", default="闭卷")
    ap.add_argument("--time", default="120 分钟")
    ap.add_argument("--date", default="", help="考试日期，留空则不打印")
    ap.add_argument("--points", type=int, default=100)
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--papers", type=int, default=3, help="套数，默认 3")
    ap.add_argument("--scores", default=None, help="各大题分值，逗号分隔")
    ap.add_argument("--no-seal", action="store_true", help="不印密封线")
    a = ap.parse_args()

    if a.list:
        print("可用预设：\n")
        for k, v in PRESETS.items():
            mix = " / ".join(f"{s['title']}{s['points']}" for s in v["plan"])
            print(f"  {k:<12} {v['label']}")
            print(f"  {'':<12} {mix}")
            print(f"  {'':<12} {v['hint']}\n")
        return 0

    if not a.course or not a.out:
        raise SystemExit("需要 --course 与 --out（或先用 --list 看预设）")

    out = Path(a.out).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"目录非空：{out}")
    out.mkdir(parents=True, exist_ok=True)

    plan = build_plan(a.preset, a.scores)
    n_sec = len(plan)

    for name in ("style.tex", "style_ans.tex"):
        shutil.copy2(ASSETS / name, out / name)

    meta = (ASSETS / "meta.tex").read_text(encoding="utf-8")

    def set_macro(text, name, value):
        pat = re.compile(r"\\newcommand\{\\" + re.escape(name) + r"\}\{[^}]*\}")
        return pat.sub(lambda m: "\\newcommand{\\" + name + "}{" + value + "}", text)

    for name, value in (("SchoolName", a.school), ("CollegeName", a.college),
                        ("CourseName", a.course), ("TermName", a.term),
                        ("MajorList", a.majors), ("ExamForm", a.form),
                        ("ExamTime", a.time), ("ExamDate", a.date),
                        ("TotalPoints", str(a.points))):
        meta = set_macro(meta, name, value)
    if a.no_seal:
        meta = set_macro(meta, "ShowSealLine", "0")
    meta = set_macro(meta, "ExamNotice", PRESET_NOTICE.get(a.preset, DEFAULT_NOTICE))
    meta = set_macro(meta, "GradeNotice", PRESET_GRADE.get(a.preset, GRADE_DEFAULT))
    (out / "meta.tex").write_text(meta, encoding="utf-8")

    # 得分表按大题数选版本
    vals = "".join("{" + str(s["points"]) + "}" for s in plan)
    macro = {4: "\\defenBiaoFour", 5: "\\defenBiaoFive", 6: "\\defenBiao"}.get(n_sec)
    if not macro:
        raise SystemExit(f"本模板支持 4–6 个大题，当前 {n_sec} 个；请合并或拆分大题")

    letters_set = ["A", "B", "C", "D", "E"][: a.papers]
    for L in letters_set:
        head = (f"% ================= {L} 卷 =================\n"
                f"% 难度定位：{'基础巩固（覆盖全部章节的最低掌握线）' if L == 'A' else ('综合应用（跨章节组合，含易错点）' if L == 'B' else '拔高挑战（综合性强、区分度高）')}\n"
                f"\\juantou{{{L}}}\n{macro}{vals}\n\n")
        (out / f"paper_{L}.tex").write_text(head + "\n".join(paper_section(s) for s in plan), encoding="utf-8")

        ahead = (f"% ===== {L} 卷参考答案与评分标准 =====\n\\anstou{{{L}}}\n\n")
        (out / f"ans_{L}.tex").write_text(ahead + "\n".join(ans_section(s) for s in plan), encoding="utf-8")

    main_p = ("\\documentclass[10.5pt,a4paper]{ctexart}\n\\input{style}\n\\begin{document}\n\\sealLine\n"
              + "".join(f"\\input{{paper_{L}}}\n" for L in letters_set) + "\\end{document}\n")
    main_a = ("\\documentclass[10.5pt,a4paper]{ctexart}\n\\input{style_ans}\n\\begin{document}\n"
              + "".join(f"\\input{{ans_{L}}}\n" for L in letters_set) + "\\end{document}\n")
    (out / "main_paper.tex").write_text(main_p, encoding="utf-8")
    (out / "main_ans.tex").write_text(main_a, encoding="utf-8")

    print(f"已生成：{out}")
    print(f"  {a.course}｜{PRESETS[a.preset]['label']}｜{a.papers} 套｜满分 {a.points}")
    for i, s in enumerate(plan):
        unit = "空" if s["kind"] == "fill" else "题"
        print(f"  {CN_NUM[i]}、{s['title']:<8}{s['points']:>4} 分   {s['n']} {unit}")
    print("\n下一步：")
    print("  1. 在 paper_A/B/C.tex 填题，ans_*.tex 填答案（编号已对齐，逐条替换占位文字即可）")
    print(f"  2. python check_exam.py {out.name}")
    print(f"  3. python build.py {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
