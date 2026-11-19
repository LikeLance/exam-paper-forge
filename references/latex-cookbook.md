# 版式与 LaTeX 速查

## 编译链

必须 **xelatex 三遍**（`.aux` → 页数引用 → 稳定），`ctexart` 文档类。

```bash
cd <exam_dir>
xelatex -interaction=nonstopmode -halt-on-error main_paper.tex   # ×3
```

字体全部做了回退，Windows / macOS / Linux 通用：

```latex
\IfFontExistsTF{SimSun}{%          % Windows 有宋体就用宋体
  \setCJKmainfont{SimSun}[BoldFont=SimHei,ItalicFont=KaiTi]}{}%
\IfFontExistsTF{Consolas}{\setmonofont{Consolas}}{}
```
没有 SimSun 时回到 ctex 默认字体（macOS 宋体 / Linux Fandol），不会编译失败。

## 结构宏

| 宏 | 作用 | 注意 |
|---|---|---|
| `\juantou{A}` | 卷头 + 切换页眉卷别 | **开头先 `\clearpage`**，见坑 1 |
| `\defenBiao{..}`×6 | 得分表，6 个大题 | 总分自动求和 |
| `\defenBiaoFive{..}`×5 | 5 个大题 | 4 个用 `\defenBiaoFour` |
| `\dati{标题}{说明}` | 大题干，带"得分/评阅人"格 | 内含 `\needspace{4.6cm}` 防孤立 |
| `\xiaoti{...}` | 小题，悬挂缩进 | 换行对齐到题号后 |
| `\kong[2.4cm]` | 填空线 | 宽度传参，按答案长度给 |
| `\kongbai{4.2cm}` | 答题空白 | 用 parbox，不可分割，不会被吞 |
| `\begin{ti}...\end{ti}` | 题目 + 答题区整体不跨页 | minipage 包裹 |
| `\sealLine` | 每页背景画密封线 | `\ShowSealLine=0` 可关 |
| `\pingfen{2 分}` | 答案册给分标注 | 内容必须 `\hbox` 包死，见坑 2 |
| `\anstou{A}` / `\datiA{}` / `\thao{}` / `\yaodian` | 答案册结构 | 在 style_ans.tex |

## 六个真实踩过的坑

### 坑 1：页眉卷别串到下一卷

`fancyhdr` 在 shipout 时取 `\juanmark` 当前值。若 A、B 卷在同一页输出，A 卷的页眉会印成"（B 卷）"。

```latex
\newcommand{\juantou}[1]{%
  \clearpage                      % ← 关键：先把上一卷的页输出掉，此时 \juanmark 还是旧值
  \renewcommand{\juanmark}{#1}%
  ...
}
```

### 坑 2：答案册某两行之间莫名空一行（最难查）

现象：`\pingfen{}` 所在行恰好排到行末时，下一行前多出一个完整行距（≈16pt），
看上去像多打了一个空行，但源文件里没有空行。

原因：`\pingfen` 里的 `\small` 改变了该行的 height/depth，TeX 行末计算 `\prevdepth` 时出现偏差。

修法：把内容包成不可断的整体盒子。

```latex
\newcommand{\pingfen}[1]{\hbox{\small\kaishu\color{black!55}（#1）}}
```

> 已实测对比：改前 Δ=39.2pt，改后 Δ=22.6pt 均匀。用 `pdftotext -bbox` 量基线差可复现。

### 坑 3：中文段落轻微越界 2–6pt

"、""，""。"连排导致可用断行点稀缺，段落被挤出右边距。

```latex
\setlength{\emergencystretch}{2em}
```
加完这一行，2–6pt 级别的 `Overfull \hbox` 基本消失。超过 10pt 的还要回源改文字（删虚词、拆长句）。

### 坑 4：得分表总分手填算错

```latex
\ExplSyntaxOn
\NewDocumentCommand{\ScoreSum}{m}{\int_eval:n {\clist_use:nn {#1} {+}}}
\ExplSyntaxOff
```
注意：`\clist_sum:n` 在部分 TeX Live 版本不存在，用 `\clist_use:nn` 拼 `+` 再 `\int_eval:n` 最稳。

### 坑 5：答题区空白被排版吞掉

用 `\vspace` 或空行留白，在页面断行处会被吃掉。用 `\parbox` 固定高度：

```latex
\newcommand{\kongbai}[1]{\par\vspace{0.12cm}\noindent
  \parbox[t][#1][t]{\linewidth}{\rule{0pt}{0pt}}\par}
```

### 坑 6：大题标题孤零零在页底

`\needspace{4.6cm}` 放在 `\dati` 开头：剩余空间不足 4.6cm 就提前换页，避免标题在页底、题目在下一页。

## TikZ 简图（计算/简答题常用）

```latex
\begin{center}
\begin{tikzpicture}[x=1cm,y=1cm,scale=0.82]
\draw[->,thick] (0,0)--(5.8,0) node[right] {\small $T$};
\draw[->,thick] (0,0)--(0,4.1) node[above] {\small $n$};
\draw[thick] (0.5,3.7)--(4.8,0.7);          % 电机机械特性
\draw[thick] (0.9,0.7)--(4.3,3.4);          % 负载特性
\fill (2.72,2.15) circle (2pt);             % 交点
\node[below left,fill=white,inner sep=1pt] at (2.62,2.06) {\scriptsize $A$};
\end{tikzpicture}
\end{center}
```

要点：`scale` 控制整体大小；`fill=white` 让标注盖住线条；字号用 `\scriptsize` 以免抢正文。

## 代码块

```latex
\lstnewenvironment{code}[1][]{\lstset{style=excode,#1}}{}
```
`style=excode` 已设等宽 7.6pt、行距 10.4pt、`columns=fullflexible`（中文注释不炸）。
代码里的 `%` 必须写成 `\%`。

## 常见改版需求

**换学校/学院**：只改 `meta.tex` 的 `\SchoolName`、`\CollegeName`。`\CollegeName` 留空则不打印。

**不印密封线**：`\ShowSealLine{0}`，或 init 时加 `--no-seal`。左边距会自动多出 1.1cm 空白，
若要去掉，把 geometry 的 `left=2.7cm` 改成 `1.6cm`。

**双面印刷**：文档类加 `twoside`，并在 `\juantou` 后加 `\thispagestyle{empty}` 处理骑缝。

**加草稿纸/答题纸**：新建 `blank.tex`，用 `\newpage` + `\begin{tikzpicture}` 画 25 行横线。

**改成 A4 两栏**：不建议。中文试卷单栏可读性明显更好，两栏会让答题区变窄。
