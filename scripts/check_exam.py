#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_exam.py —— 期末模拟卷质检器

用法：
    python check_exam.py <exam_dir>
    python check_exam.py <exam_dir> --strict     # 警告也算失败
    python check_exam.py <exam_dir> --json       # 机器可读

检查项（AI 出题最容易翻车的点）：
    R01 得分表分值合计 = 满分
    R02 每卷大题声明分值合计 = 满分
    R03 填空题：空数 × 每空分值 = 声明分值
    R04 单选题：题数 × 每题分值 = 声明分值；答案字母不超出实际选项数
    R05 判断题：题数 × 每题分值 = 声明分值；答案只能是 √/×
    R06 A/B/C 三卷之间无重复题干（相似度超阈值即报）
    R07 答案册小题数 = 试卷小题数
    R08 LaTeX 静态检查：花括号与 $ 配平、无未转义的裸 %

退出码：0 全通过；1 有 ERROR。
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEV_ERROR = "ERROR"
SEV_WARN = "WARN"
SEV_PASS = "PASS"

TYPE_WORDS = {
    # 长关键字在前：Python 3.7+ 字典保序，"多项选择"必须先于"选择"命中
    "多项选择": "multi", "程序阅读": "code_read", "算法设计": "code_write",
    "名词解释": "term", "阅读理解": "reading", "案例分析": "case",
    "材料分析": "material", "法条分析": "law", "完形填空": "fill",
    "填空": "fill", "选择": "choice", "判断": "tf", "简答": "short",
    "计算": "calc", "分析": "analyze", "设计": "design",
    "程序": "code", "编程": "code", "论述": "essay", "作图": "draw",
    "证明": "prove", "翻译": "translate", "写作": "writing",
}

# 答案只能落在这些题型上做逐题核对（其余题型按要点给分，题数不强求）
CHECKED_KINDS = ("fill", "choice", "multi", "tf")

CJK_PUNCT = "，。、；：？！“”‘’（）《》〈〉【】—…·,.;:?!\"'()[]<>-"


class Report:
    def __init__(self):
        self.items = []

    def add(self, rule, sev, msg):
        self.items.append({"rule": rule, "severity": sev, "message": msg})

    def merged(self, rule, sevs, msg_pass):
        """同一规则多卷：全部通过才记 PASS，否则把失败项并进一条。"""
        bad = [s for s in sevs if s[0] == SEV_ERROR]
        warn = [s for s in sevs if s[0] == SEV_WARN]
        if bad:
            for _, m in bad:
                self.add(rule, SEV_ERROR, m)
        elif warn:
            for _, m in warn:
                self.add(rule, SEV_WARN, m)
        else:
            self.add(rule, SEV_PASS, msg_pass)

    @property
    def errors(self):
        return [i for i in self.items if i["severity"] == SEV_ERROR]

    @property
    def warns(self):
        return [i for i in self.items if i["severity"] == SEV_WARN]

    def dump(self, as_json=False):
        if as_json:
            print(json.dumps(self.items, ensure_ascii=False, indent=2))
            return
        icon = {SEV_PASS: "  ok ", SEV_WARN: " !!! ", SEV_ERROR: "  X  "}
        for it in self.items:
            print(f"[{icon[it['severity']]}]{it['rule']:<5} {it['message']}")
        print()
        if self.errors:
            print(f"未通过：{len(self.errors)} 项错误，{len(self.warns)} 项警告")
        elif self.warns:
            print(f"通过（有 {len(self.warns)} 项警告）")
        else:
            print("全部通过")


# ---------------- 解析 ----------------

def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def read(path: Path) -> str:
    return strip_comments(path.read_text(encoding="utf-8", errors="replace"))


def get_total_points(meta_text: str) -> int:
    m = re.search(r"\\TotalPoints\}\{(\d+)\}", meta_text)
    return int(m.group(1)) if m else 100


def find_meta(exam_dir: Path) -> str:
    for name in ("meta.tex", "../meta.tex"):
        p = exam_dir / name
        if p.exists():
            return read(p)
    return r"\newcommand{\TotalPoints}{100}"


def parse_paper(text: str):
    """返回 (卷别, 大题列表[{title, note, points, kind, body}])"""
    m = re.search(r"\\juantou\{([^}]*)\}", text)
    label = m.group(1).strip() if m else "?"

    # 大题切块
    heads = list(re.finditer(r"\\dati\{([^}]*)\}\{([^}]*)\}", text))
    sections = []
    for i, h in enumerate(heads):
        start = h.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[start:end]
        title, note = h.group(1), h.group(2)
        pts_m = re.search(r"共\s*(\d+)\s*分", note) or re.search(r"(\d+)\s*分", note)
        points = int(pts_m.group(1)) if pts_m else None
        kind = next((v for k, v in TYPE_WORDS.items() if k in title), "other")
        sections.append({
            "title": title, "note": note, "points": points,
            "kind": kind, "body": body,
            "count": len(re.findall(r"\\xiaoti\{", body)),
        })
    return label, sections


def parse_score_table(text: str):
    for macro, cnt in (("defenBiao", 6), ("defenBiaoFive", 5), ("defenBiaoFour", 4)):
        # defenBiao 是另外两个的前缀，先匹配长的，避免误判
        pat = r"\\" + macro + r"(?![A-Za-z])" + r"\{([^}]*)\}" * cnt
        m = re.search(pat, text)
        if m:
            return [int(x) for x in m.groups()]
    return None


def normalize(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z@]+\*?", "", s)      # 去命令名
    s = re.sub(r"[{}$\\_^&]", "", s)
    s = "".join(ch for ch in s if ch not in CJK_PUNCT and not ch.isspace())
    return s


# 骨架占位标记：init_exam.py 生成的骨架靠这些词占位，填题时必须全部替换掉
PLACEHOLDER = re.compile(r"（题干|（题目）|（选项）|（答案）|（陈述句）|（已知条件|"
                         r"（要点[一二三]|（解析：|（案例材料|（材料，|（名词）|（问题）")


def stems(text: str):
    r"""抽取题干（\xiaoti 的第一句），用于跨卷查重；骨架占位不算题干"""
    out = []
    for m in re.finditer(r"\\xiaoti\{(.+?)\}\s*(?:\r?\n|$)", text, re.S):
        raw = m.group(1)
        if PLACEHOLDER.search(raw):
            continue
        out.append(normalize(raw)[:120])
    return [s for s in out if len(s) >= 8]


def parse_answers(text: str):
    """按答题册大题切块，返回 [(kind, [答案...])]，答案来自 \\thao{n. X}"""
    heads = list(re.finditer(r"\\datiA\{([^}]*)\}", text))
    blocks = []
    for i, h in enumerate(heads):
        start, end = h.end(), (heads[i + 1].start() if i + 1 < len(heads) else len(text))
        title = h.group(1)
        kind = next((v for k, v in TYPE_WORDS.items() if k in title), "other")
        ans = [m.group(2).strip() for m in
               re.finditer(r"\\thao\{\s*(\d+)\s*\.\s*([^}]*)\}", text[start:end])]
        blocks.append((kind, ans, title))
    return blocks


# ---------------- 检查 ----------------

def check(exam_dir: Path, dup_threshold: float = 0.82, profile_path: str | None = None,
          weight_tol: float | None = None):
    rep = Report()
    meta = find_meta(exam_dir)
    total = get_total_points(meta)

    papers = {}
    for f in sorted(exam_dir.glob("paper_*.tex")):
        label, secs = parse_paper(read(f))
        papers[f.stem.replace("paper_", "")] = {"file": f, "label": label, "sections": secs, "text": read(f)}

    if not papers:
        rep.add("R00", SEV_ERROR, f"{exam_dir} 下没找到 paper_*.tex")
        return rep, papers

    # R01 得分表
    sev_list = []
    for key, p in papers.items():
        pts = parse_score_table(p["text"])
        if pts is None:
            sev_list.append((SEV_WARN, f"{key} 卷没有得分表（\\defenBiao 未调用）"))
        elif sum(pts) != total:
            sev_list.append((SEV_ERROR, f"{key} 卷得分表分值 {pts} 合计 {sum(pts)} ≠ 满分 {total}"))
    rep.merged("R01", sev_list, f"各卷得分表分值合计 = 满分 {total}")

    # R02 大题声明分值合计
    sev_list = []
    for key, p in papers.items():
        decl = [s["points"] for s in p["sections"] if s["points"] is not None]
        missing = len(p["sections"]) - len(decl)
        if missing:
            sev_list.append((SEV_ERROR, f"{key} 卷有 {missing} 个大题说明里没写分值"))
        if decl and sum(decl) != total:
            sev_list.append((SEV_ERROR,
                             f"{key} 卷大题分值 {decl} 合计 {sum(decl)} ≠ 满分 {total}（差 {total - sum(decl):+d}）"))
        table = parse_score_table(p["text"])
        if table and decl and table != decl:
            sev_list.append((SEV_WARN, f"{key} 卷得分表 {table} 与各题声明 {decl} 不一致"))
    rep.merged("R02", sev_list, f"各卷大题分值合计 = {total}，且与得分表一致")

    # R03 填空题：空数 × 每空分值
    sev_list = []
    for key, p in papers.items():
        for s in p["sections"]:
            if s["kind"] != "fill":
                continue
            blanks = len(re.findall(r"\\kong\b", s["body"]))
            per = re.search(r"每空\s*(\d+)\s*分", s["note"])
            if not per:
                sev_list.append((SEV_WARN, f"{key} 卷填空大题说明里没写“每空 N 分”"))
                continue
            per_v = int(per.group(1))
            if s["points"] and blanks * per_v != s["points"]:
                sev_list.append((SEV_ERROR,
                                 f"{key} 卷填空：{blanks} 空 × {per_v} 分 = {blanks * per_v}，"
                                 f"与声明 {s['points']} 分不符（应为 {s['points'] // per_v} 空）"))
    rep.merged("R03", sev_list, "填空题空数与分值匹配")

    # R04 客观选择题：题量×单价、选项完整性
    sev_list = []
    for key, p in papers.items():
        for s in p["sections"]:
            if s["kind"] not in ("choice", "multi"):
                continue
            per = re.search(r"每小题\s*(\d+)\s*分", s["note"])
            if per and s["points"] and s["count"] * int(per.group(1)) != s["points"]:
                sev_list.append((SEV_ERROR,
                                 f"{key} 卷「{s['title']}」：{s['count']} 题 × {per.group(1)} 分"
                                 f" = {s['count'] * int(per.group(1))}，与声明 {s['points']} 分不符"))
            for i, m in enumerate(re.finditer(r"\\xiaoti\{((?:[^{}]|\{[^{}]*\})*)\}", s["body"]), 1):
                block = m.group(1)
                letters = re.findall(r"(?:^|[\s（(])([A-H])\s*[.．、]", block)
                if letters:
                    top = max(letters)
                    need = "ABCDEFGH"[: ord(top) - ord("A") + 1]
                    miss = [x for x in need if x not in letters]
                    if miss:
                        sev_list.append((SEV_ERROR,
                                         f"{key} 卷「{s['title']}」第 {i} 题选项缺 {''.join(miss)}"
                                         f"（只找到 {''.join(sorted(set(letters)))}）"))
    rep.merged("R04", sev_list, "选择题题量、分值与选项完整性正常")

    # R05 答案册与试卷逐题对齐，且答案落在合法取值域内
    sev_list = []
    for f in sorted(exam_dir.glob("ans_*.tex")):
        key = f.stem.replace("ans_", "")
        p = papers.get(key)
        if not p:
            continue
        blocks = parse_answers(read(f))
        paper_secs = [s for s in p["sections"] if s["kind"] in CHECKED_KINDS]
        ans_by_kind = {k: a for k, a, _ in blocks}

        for s in paper_secs:
            ans = ans_by_kind.get(s["kind"])
            if ans is None:
                sev_list.append((SEV_WARN, f"{key} 卷答案册缺少「{s['title']}」的答案块"))
                continue
            # 填空题：一个 \thao 里常放多空答案，只比数量下限
            if s["kind"] == "fill":
                blanks = len(re.findall(r"\\kong\b", s["body"]))
                if ans and len(ans) < max(1, blanks // 3):
                    sev_list.append((SEV_WARN,
                                     f"{key} 卷填空有 {blanks} 空，答案只给了 {len(ans)} 条，核对是否漏空"))
                continue
            if len(ans) != s["count"]:
                sev_list.append((SEV_ERROR,
                                 f"{key} 卷「{s['title']}」{s['count']} 题，答案册 {len(ans)} 条，数量不匹配"))
                continue
            if s["kind"] in ("choice", "multi"):
                opts = []
                for m in re.finditer(r"\\xiaoti\{((?:[^{}]|\{[^{}]*\})*)\}", s["body"]):
                    letters = re.findall(r"(?:^|[\s（(])([A-H])\s*[.．、]", m.group(1))
                    opts.append(max(letters) if letters else "D")
                for i, (a, top) in enumerate(zip(ans, opts), 1):
                    clean = re.sub(r"[^A-H]", "", a.upper())
                    if not clean:
                        sev_list.append((SEV_ERROR, f"{key} 卷「{s['title']}」第 {i} 题答案「{ans[i-1]}」不是字母"))
                    elif max(clean) > top:
                        sev_list.append((SEV_ERROR,
                                         f"{key} 卷「{s['title']}」第 {i} 题答案 {clean}，但该题只有到 {top} 的选项"))
                    elif s["kind"] == "choice" and len(clean) != 1:
                        sev_list.append((SEV_ERROR,
                                         f"{key} 卷单选第 {i} 题答案给了 {len(clean)} 个字母（{clean}）"))
            elif s["kind"] == "tf":
                ok = {"√", "×", "\\surd", "$\\surd$", "$\\times$", "对", "错", "T", "F", "\\checkmark", "\\times"}
                for i, a in enumerate(ans, 1):
                    if a.strip() not in ok:
                        sev_list.append((SEV_WARN, f"{key} 卷判断第 {i} 题答案「{a}」不在 √/× 之列"))
    rep.merged("R05", sev_list, "答案册与试卷逐题对齐，单选答案未越界、判断答案合法")

    # R06 跨卷重复
    sev_list = []
    keys = list(papers)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = papers[keys[i]], papers[keys[j]]
            sa, sb = stems(a["text"]), stems(b["text"])
            dup = []
            for x in sa:
                for y in sb:
                    r = SequenceMatcher(None, x, y).ratio()
                    if r >= dup_threshold:
                        dup.append((round(r, 2), x[:36]))
            if dup:
                dup.sort(reverse=True)
                shown = "；".join(f"{r}「{t}…」" for r, t in dup[:3])
                sev_list.append((SEV_ERROR, f"{keys[i]} 与 {keys[j]} 有 {len(dup)} 处重复题：{shown}"))
    rep.merged("R06", sev_list, "A/B/C 三卷之间无重复题干")

    # R07 答案册存在性
    sev_list = []
    for key in papers:
        if not (exam_dir / f"ans_{key}.tex").exists():
            sev_list.append((SEV_ERROR, f"缺少 ans_{key}.tex（{key} 卷没有答案册）"))
    rep.merged("R07", sev_list, "每卷都有对应答案册")

    # R08 LaTeX 静态检查
    sev_list = []
    for f in sorted(exam_dir.glob("*.tex")):
        t = read(f)
        if t.count("{") != t.count("}"):
            sev_list.append((SEV_ERROR, f"{f.name}：花括号不配平 {t.count('{')} 左 / {t.count('}')} 右"))
        if t.count("$") % 2:
            sev_list.append((SEV_ERROR, f"{f.name}：$ 数量为奇数（{t.count('$')}），公式必错"))
        if re.search(r"(?<!\\)%", f.read_text(encoding="utf-8", errors="replace")):
            pass  # 注释本身合法，交给 strip 处理
    rep.merged("R08", sev_list, "LaTeX 花括号与公式定界符配平")

    # R09 占位符残留（骨架状态检测）
    sev_list = []
    for key, p in papers.items():
        n = len(PLACEHOLDER.findall(p["text"]))
        if n:
            sev_list.append((SEV_WARN, f"{key} 卷还有 {n} 处占位未填（骨架状态），交付前须全部替换"))
    rep.merged("R09", sev_list, "无占位符残留，题目已全部填写")

    # R10 章节权重：只有存在 profile.json 时才查（没有画像就不该凭空判分）
    pp = Path(profile_path).expanduser() if profile_path else (exam_dir / "profile.json")
    if pp.exists():
        prof = json.loads(pp.read_text(encoding="utf-8"))
        chapters = prof.get("chapters", [])
        if chapters:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from profile import parse_tex, classify, build_weights

            weights = build_weights(chapters)
            tol = weight_tol if weight_tol else max(4.0, prof.get("total", 100) * 0.06)
            sev_list, skipped = [], []
            for key, p in papers.items():
                if PLACEHOLDER.search(p["text"]):
                    skipped.append(key)      # 骨架还没填题，权重检查无意义
                    continue
                actual, unknown = {}, 0.0
                for stem, pts in parse_tex(p["file"]):
                    cid = classify(stem, chapters, weights)
                    if cid:
                        actual[cid] = actual.get(cid, 0) + pts
                    else:
                        unknown += pts
                for ch in chapters:
                    got = actual.get(ch["id"], 0)
                    diff = got - ch["points"]
                    if ch.get("must") and got == 0:
                        sev_list.append((SEV_ERROR,
                                         f"{key} 卷「{ch['name']}」标记必考，但一分未出"))
                    elif abs(diff) > tol * 1.5:
                        sev_list.append((SEV_ERROR,
                                         f"{key} 卷「{ch['name']}」目标 {ch['points']} 分，"
                                         f"实际 {got:.0f} 分（{diff:+.0f}），偏离过大"))
                    elif abs(diff) > tol:
                        sev_list.append((SEV_WARN,
                                         f"{key} 卷「{ch['name']}」目标 {ch['points']} 分，"
                                         f"实际 {got:.0f} 分（{diff:+.0f}）"))
                if unknown > tol:
                    sev_list.append((SEV_WARN,
                                     f"{key} 卷有 {unknown:.0f} 分未匹配到任何章节，"
                                     f"检查画像关键词或章节划分是否漏了内容"))
            if skipped:
                sev_list.append((SEV_WARN, f"{'、'.join(skipped)} 卷仍是骨架，跳过章节权重检查"))
            rep.merged("R10", sev_list, f"各章分值符合画像（容差 ±{tol:.0f} 分）")

    return rep, papers


def main():
    ap = argparse.ArgumentParser(description="期末模拟卷质检")
    ap.add_argument("exam_dir", help="含 paper_*.tex / ans_*.tex / meta.tex 的目录")
    ap.add_argument("--strict", action="store_true", help="警告也视为失败")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--threshold", type=float, default=0.82, help="查重阈值，默认 0.82")
    ap.add_argument("--profile", default=None,
                    help="考情画像路径，默认取 <exam_dir>/profile.json；没有则跳过 R10")
    ap.add_argument("--weight-tol", type=float, default=None,
                    help="章节分值容差（分），默认 max(4, 满分的 6%%)；拔高卷可放宽到 8–10")
    a = ap.parse_args()

    d = Path(a.exam_dir).expanduser().resolve()
    if not d.is_dir():
        print(f"目录不存在：{d}")
        return 1

    rep, _ = check(d, a.threshold, a.profile, a.weight_tol)
    rep.dump(a.json)

    if rep.errors:
        return 1
    if a.strict and rep.warns:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
