# -*- coding: utf-8 -*-
"""生成大学数学种子题库 → data/bank/math_bank.json
线代 20 题 + 数分 21 题，挂接知识图谱真实 KP id，全部含解析。"""
import io, json, os, sys, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "bank", "math_bank.json")


def q(id, subject, kps, qtype, diff, stem, answer, solution, options=None, source="知源学伴种子题库"):
    d = {"id": id, "subject": subject, "kp_ids": kps, "type": qtype, "difficulty": diff,
         "stem": stem, "answer": answer, "solution": solution, "score": 10,
         "source": source, "created": time.time(), "updated": time.time()}
    if options:
        d["options"] = [{"key": k, "text": t} for k, t in options]
    return d


LA, CA = "linear_algebra", "calculus"
Q = []

# ---------------- 线性代数 ----------------
Q += [
    q("MQ-0001", LA, ["la_det"], "choice", "basic",
      "计算 $\\begin{vmatrix}2&1\\\\3&4\\end{vmatrix}$ 的值为（　）。", "A",
      "二阶行列式按对角线法则：$2\\times4-1\\times3=5$。",
      [("A", "5"), ("B", "8"), ("C", "11"), ("D", "2")]),
    q("MQ-0002", LA, ["la_det"], "solve", "basic",
      "计算四阶上三角行列式 $\\begin{vmatrix}1&0&0&0\\\\0&2&0&0\\\\0&0&3&0\\\\0&0&0&4\\end{vmatrix}$。",
      "24",
      "上三角行列式等于主对角元之积：$1\\cdot2\\cdot3\\cdot4=24$。"),

    q("MQ-0003", LA, ["la_matrix"], "fill", "basic",
      "设 $A=\\begin{pmatrix}1&2\\\\0&1\\end{pmatrix}$，则 $A^2=$ ______。",
      "$\\begin{pmatrix}1&4\\\\0&1\\end{pmatrix}$",
      "矩阵乘法：第一行乘第一列得 1，第一行乘第二列得 $1\\cdot2+2\\cdot1=4$，第二行不变。"),
    q("MQ-0004", LA, ["la_matrix"], "choice", "mid",
      "设 $A,B$ 均为 $n$ 阶方阵，且 $AB=O$，则下列结论正确的是（　）。", "C",
      "矩阵乘法存在零因子，$AB=O$ 不能推出 $A=O$ 或 $B=O$（如 $A\\ne O,B\\ne O$ 时仍可能有 $AB=O$）；仅当其中之一可逆时才能推出另一个为 $O$。",
      [("A", "$A=O$ 或 $B=O$"), ("B", "$|A|=0$ 且 $|B|=0$"),
       ("C", "不能推出 $A=O$ 或 $B=O$"), ("D", "$A=B=O$")]),

    q("MQ-0005", LA, ["la_inverse"], "fill", "basic",
      "设 $A=\\begin{pmatrix}2&5\\\\1&3\\end{pmatrix}$，则 $A^{-1}=$ ______。",
      "$\\begin{pmatrix}3&-5\\\\-1&2\\end{pmatrix}$",
      "$|A|=6-5=1\\ne0$，$A^{-1}=\\dfrac{1}{|A|}\\begin{pmatrix}3&-5\\\\-1&2\\end{pmatrix}$。"),
    q("MQ-0006", LA, ["la_inverse"], "solve", "hard",
      "证明：若 $n$ 阶方阵 $A$ 可逆，则 $(A^{T})^{-1}=(A^{-1})^{T}$。",
      "$(A^{T})^{-1}=(A^{-1})^{T}$",
      "因为 $A^{T}(A^{-1})^{T}=(A^{-1}A)^{T}=E$，且 $(A^{-1})^{T}A^{T}=(AA^{-1})^{T}=E$，"
      "由逆矩阵定义，$(A^{-1})^{T}$ 是 $A^{T}$ 的逆矩阵，即 $(A^{T})^{-1}=(A^{-1})^{T}$。"),

    q("MQ-0007", LA, ["la_rank"], "fill", "basic",
      "矩阵 $\\begin{pmatrix}1&2&3\\\\2&4&6\\\\3&6&9\\end{pmatrix}$ 的秩为 ______。", "1",
      "三行均成比例（第 2、3 行分别是第 1 行的 2、3 倍），行秩为 1，故 $r(A)=1$。"),
    q("MQ-0008", LA, ["la_rank"], "choice", "basic",
      "$n$ 阶方阵 $A$ 可逆的充要条件是（　）。", "A",
      "$A$ 可逆 $\\Leftrightarrow |A|\\ne0\\Leftrightarrow r(A)=n\\Leftrightarrow$ 列（行）向量组线性无关。",
      [("A", "$r(A)=n$"), ("B", "$|A|=0$"), ("C", "$A$ 的列向量组线性相关"), ("D", "$A^2=A$")]),

    q("MQ-0009", LA, ["la_eq"], "choice", "basic",
      "$n$ 元齐次线性方程组 $Ax=0$ 有非零解的充要条件是（　）。", "B",
      "齐次方程组永远有零解；有非零解 $\\Leftrightarrow r(A)<n$（自由未知量个数 $n-r(A)>0$）。",
      [("A", "$r(A)=n$"), ("B", "$r(A)<n$"), ("C", "$|A|\\ne0$"), ("D", "方程个数等于未知数个数")]),
    q("MQ-0010", LA, ["la_eq"], "solve", "hard",
      "讨论 $\\lambda$ 取何值时，方程组 $\\begin{cases}x+y=1\\\\ \\lambda x+y=\\lambda\\end{cases}$ 解的情况。",
      "$\\lambda\\ne1$ 时有唯一解 $x=1,\\ y=0$；$\\lambda=1$ 时有无穷多解",
      "两式相减得 $(\\lambda-1)x=\\lambda-1$。当 $\\lambda\\ne1$ 时 $x=1$，代回得 $y=0$，唯一解；"
      "当 $\\lambda=1$ 时两方程相同，令 $y=t$ 得 $x=1-t$，无穷多解。"),

    q("MQ-0011", LA, ["la_vector"], "choice", "basic",
      "向量组线性相关的充要条件是（　）。", "A",
      "向量组（$s\\ge2$）线性相关 $\\Leftrightarrow$ 至少有一个向量可由其余向量线性表示；B、C、D 都只是充分或无关条件。",
      [("A", "其中至少有一个向量可由其余向量线性表示"), ("B", "其中含零向量"),
       ("C", "向量个数大于维数"), ("D", "任意两个向量都成比例")]),
    q("MQ-0012", LA, ["la_vector"], "fill", "basic",
      "向量 $\\alpha_1=(1,2)^{T}$ 与 $\\alpha_2=(2,4)^{T}$ 线性 ______（填“相关”或“无关”）。", "相关",
      "$\\alpha_2=2\\alpha_1$，成比例即线性相关。"),

    q("MQ-0013", LA, ["la_eigen"], "fill", "basic",
      "矩阵 $A=\\begin{pmatrix}2&1\\\\1&2\\end{pmatrix}$ 的全部特征值为 ______。",
      "$3$ 和 $1$",
      "$|\\lambda E-A|=(\\lambda-2)^2-1=0$，解得 $\\lambda_1=3,\\ \\lambda_2=1$。"),
    q("MQ-0014", LA, ["la_eigen"], "solve", "mid",
      "求 $A=\\begin{pmatrix}3&1\\\\0&2\\end{pmatrix}$ 的特征值与对应的特征向量。",
      "$\\lambda=3$ 对应 $\\xi_1=(1,0)^{T}$；$\\lambda=2$ 对应 $\\xi_2=(-1,1)^{T}$",
      "$|\\lambda E-A|=(\\lambda-3)(\\lambda-2)=0$，$\\lambda_1=3,\\lambda_2=2$。"
      "对 $\\lambda=3$：$(3E-A)x=0$ 得 $x_2=0$，取 $\\xi_1=(1,0)^{T}$；"
      "对 $\\lambda=2$：$(2E-A)x=0$ 即 $-x_1+x_2=0$，取 $\\xi_2=(-1,1)^{T}$。"),

    q("MQ-0015", LA, ["la_diag"], "choice", "mid",
      "$n$ 阶矩阵 $A$ 可相似对角化的充要条件是（　）。", "A",
      "$A$ 可对角化 $\\Leftrightarrow$ $A$ 有 $n$ 个线性无关的特征向量；有 $n$ 个互异特征值只是充分条件。",
      [("A", "$A$ 有 $n$ 个线性无关的特征向量"), ("B", "$A$ 有 $n$ 个互异的特征值"),
       ("C", "$A$ 是对称矩阵"), ("D", "$A$ 可逆")]),
    q("MQ-0016", LA, ["la_diag"], "fill", "mid",
      "判断：$A=\\begin{pmatrix}1&1\\\\0&1\\end{pmatrix}$ 能否相似对角化？______（填“能”或“不能”并简述理由）。",
      "不能：特征值 $\u03bb=1$ 为二重根但只有一个线性无关特征向量",
      "$|\\lambda E-A|=(\\lambda-1)^2=0$，特征值 1 为二重根；$(E-A)x=0$ 得 $x_2=0$，"
      "线性无关特征向量只有 1 个 < 2，故不能对角化。"),

    q("MQ-0017", LA, ["la_quad"], "fill", "basic",
      "二次型 $f(x_1,x_2)=x_1^{2}+2x_1x_2+3x_2^{2}$ 的矩阵为 ______。",
      "$\\begin{pmatrix}1&1\\\\1&3\\end{pmatrix}$",
      "交叉项 $2x_1x_2$ 拆成对称两半各记 $1$，对角项分别为 $1,3$。"),
    q("MQ-0018", LA, ["la_quad"], "choice", "mid",
      "$n$ 元实二次型 $f=x^{T}Ax$ 正定的充要条件是（　）。", "A",
      "正定 $\\Leftrightarrow$ 各阶顺序主子式全大于零 $\\Leftrightarrow$ 特征值全大于零；B、C、D 均不是充要条件。",
      [("A", "$A$ 的各阶顺序主子式都大于零"), ("B", "$A$ 的特征值全小于零"),
       ("C", "$|A|>0$"), ("D", "$r(A)=n$")]),

    q("MQ-0019", LA, ["la_space"], "fill", "mid",
      "$\\mathbb{R}^3$ 的子空间 $W=\\{(x,y,z)^{T}: x+y+z=0\\}$ 的维数为 ______。", "2",
      "一个线性方程约束三个自由变量，解空间维数 $=3-r=3-1=2$（基础解系含 2 个向量）。"),
    q("MQ-0020", LA, ["la_space"], "choice", "basic",
      "向量空间 $V$ 的一组基是指 $V$ 中的向量组，它（　）。", "A",
      "基的定义：线性无关，且 $V$ 中任一向量都可由它线性表示。",
      [("A", "线性无关，且 V 中任一向量都可由它线性表示"), ("B", "是 V 中任意的极大向量组"),
       ("C", "两两正交"), ("D", "包含零向量")]),
]

# ---------------- 数学分析 ----------------
Q += [
    q("MQ-0101", CA, ["ca_seq"], "fill", "basic",
      "$\\lim\\limits_{n\\to\\infty}\\left(1+\\dfrac{1}{n}\\right)^{n}=$ ______。", "$e$",
      "重要极限：数列 $(1+1/n)^n$ 单调递增有上界，极限为自然对数的底 $e\\approx2.718$。"),
    q("MQ-0102", CA, ["ca_seq"], "choice", "basic",
      "若数列 $\\{a_n\\}$ 收敛，则下列结论必然成立的是（　）。", "A",
      "收敛 $\\Rightarrow$ 有界（必要条件）；有界不一定收敛（如 $(-1)^n$）；单调性与连续性均无从保证。",
      [("A", "$\\{a_n\\}$ 有界"), ("B", "$\\{a_n\\}$ 单调"), ("C", "$\\{a_n\\}$ 发散"), ("D", "以上都不对")]),

    q("MQ-0103", CA, ["ca_func"], "fill", "basic",
      "$\\lim\\limits_{x\\to0}\\dfrac{\\sin x}{x}=$ ______。", "1",
      "第一重要极限（夹逼或泰勒：$\\sin x = x + o(x)$）。"),
    q("MQ-0104", CA, ["ca_func"], "choice", "basic",
      "函数 $f$ 在 $x_0$ 连续的充要条件是（　）。", "A",
      "连续定义：$\\lim_{x\\to x_0}f(x)=f(x_0)$，即极限存在且等于该点函数值。",
      [("A", "极限存在且等于 f(x_0)"), ("B", "左右极限存在"), ("C", "f 在 x_0 可导"), ("D", "f 在 x_0 附近单调")]),

    q("MQ-0105", CA, ["ca_deriv"], "fill", "basic",
      "$\\dfrac{d}{dx}\\left(x^{2}e^{x}\\right)=$ ______。", "$(x^2+2x)e^x$",
      "乘积法则：$(x^2)'e^x+x^2(e^x)'=2xe^x+x^2e^x=(x^2+2x)e^x$。"),
    q("MQ-0106", CA, ["ca_deriv"], "choice", "basic",
      "关于可导与连续的关系，正确的是（　）。", "A",
      "可导必连续（一阶可导即可微，可微必连续）；反之不成立，如 $|x|$ 在 0 处连续但不可导。",
      [("A", "可导必连续"), ("B", "连续必可导"), ("C", "可导与连续无关"), ("D", "连续必可微")]),

    q("MQ-0107", CA, ["ca_mvt"], "choice", "basic",
      "罗尔定理的三个条件是（　）。", "A",
      "Rolle 定理：闭区间连续、开区间可导、端点函数值相等；三者缺一不可。",
      [("A", "[a,b] 连续、(a,b) 可导、f(a)=f(b)"), ("B", "只需 (a,b) 内可导"),
       ("C", "只需 [a,b] 连续"), ("D", "f 在 [a,b] 单调")]),
    q("MQ-0108", CA, ["ca_mvt"], "fill", "basic",
      "拉格朗日中值定理：$f(b)-f(a)=$ ______（写出含 $\\xi$ 的表达式，$\\xi\\in(a,b)$）。",
      "$f'(\\xi)(b-a)$",
      "拉格朗日中值公式，是罗尔定理推广到端点值不相等的情形。"),

    q("MQ-0109", CA, ["ca_int_indef"], "fill", "basic",
      "$\\int 2x\\,dx=$ ______。", "$x^2+C$",
      "基本积分公式；切记不要漏写任意常数 $C$。"),
    q("MQ-0110", CA, ["ca_int_indef"], "solve", "basic",
      "计算 $\\int xe^{x^{2}}\\,dx$。",
      "$\\dfrac{1}{2}e^{x^{2}}+C$",
      "凑微分：$x\\,dx=\\dfrac12 d(x^2)$，原式 $=\\dfrac12\\int e^{x^2}d(x^2)=\\dfrac12 e^{x^2}+C$。"),

    q("MQ-0111", CA, ["ca_int_def"], "fill", "basic",
      "$\\int_{0}^{1}x^{2}\\,dx=$ ______。", "$\\dfrac{1}{3}$",
      "牛顿—莱布尼茨公式：$\\left[\\dfrac{x^3}{3}\\right]_0^1=\\dfrac13$。"),
    q("MQ-0112", CA, ["ca_int_def"], "choice", "basic",
      "$\\int_{-1}^{1}x^{3}\\,dx=$（　）。", "A",
      "$x^3$ 是奇函数，对称区间上奇函数积分为 0。",
      [("A", "0"), ("B", "$\\frac12$"), ("C", "2"), ("D", "不存在")]),

    q("MQ-0113", CA, ["ca_series_num"], "choice", "basic",
      "$p$-级数 $\\sum\\limits_{n=1}^{\\infty}\\dfrac{1}{n^{2}}$ 的收敛性是（　）。", "A",
      "$p=2>1$，$p$-级数收敛；对比调和级数 $\\sum 1/n$（$p=1$）发散。",
      [("A", "收敛"), ("B", "发散"), ("C", "条件收敛"), ("D", "无法判断")]),
    q("MQ-0114", CA, ["ca_series_num"], "fill", "basic",
      "等比级数 $\\sum\\limits_{n=0}^{\\infty}\\dfrac{1}{2^{n}}$ 的和为 ______。", "2",
      "公比 $q=\\dfrac12$，$|q|<1$，和 $=\\dfrac{1}{1-q}=2$。"),

    q("MQ-0115", CA, ["ca_series_pow"], "fill", "mid",
      "幂级数 $\\sum\\limits_{n=1}^{\\infty}\\dfrac{x^{n}}{n}$ 的收敛半径 $R=$ ______。", "1",
      "$\\lim\\limits_{n\\to\\infty}\\dfrac{a_{n+1}}{a_n}=\\lim\\dfrac{n}{n+1}=1$，故 $R=1$（$x=1$ 发散、$x=-1$ 收敛）。"),
    q("MQ-0116", CA, ["ca_series_pow"], "choice", "basic",
      "若 $\\lim\\limits_{n\\to\\infty}\\left|\\dfrac{a_{n+1}}{a_n}\\right|=4$，则幂级数 $\\sum a_n x^{n}$ 的收敛半径 $R=$（　）。", "B",
      "比值法：$R=\\dfrac{1}{4}=\\dfrac14$。",
      [("A", "4"), ("B", "$\\frac14$"), ("C", "2"), ("D", "$+\\infty$")]),

    q("MQ-0117", CA, ["ca_multi"], "fill", "basic",
      "$z=x^{2}+y^{2}$，则 $\\dfrac{\\partial z}{\\partial x}=$ ______。", "$2x$",
      "对 $x$ 求偏导时把 $y$ 视为常数。"),
    q("MQ-0118", CA, ["ca_multi"], "choice", "mid",
      "关于偏导数与可微的关系，正确的是（　）。", "A",
      "偏导数连续 $\\Rightarrow$ 可微；可微 $\\Rightarrow$ 偏导存在；但偏导存在不足以保证可微。",
      [("A", "偏导数连续 ⇒ 可微"), ("B", "可微 ⇒ 偏导数连续"),
       ("C", "偏导数存在 ⇒ 可微"), ("D", "两者互不相关")]),

    q("MQ-0119", CA, ["ca_multi_int"], "fill", "basic",
      "$\\iint\\limits_{D}dx\\,dy$，其中 $D$ 为单位圆盘 $x^2+y^2\\le1$，值为 ______。", "$\\pi$",
      "二重积分 $\\iint_D d\\sigma$ 的几何意义是区域 $D$ 的面积，单位圆面积为 $\\pi$。"),
    q("MQ-0120", CA, ["ca_multi_int"], "choice", "basic",
      "在计算二重积分时“交换积分次序”的主要目的是（　）。", "A",
      "某些次序下内层积分原函数难求或积分限复杂，交换次序可简化计算。",
      [("A", "简化积分计算"), ("B", "改变积分符号"), ("C", "判断收敛性"), ("D", "消除奇偶性")]),

    q("MQ-0121", CA, ["ca_ode"], "fill", "basic",
      "微分方程 $y'=y$ 的通解为 ______。", "$y=Ce^{x}$",
      "分离变量：$\\dfrac{dy}{y}=dx \\Rightarrow \\ln|y|=x+C_1 \\Rightarrow y=Ce^x$。"),
    q("MQ-0122", CA, ["ca_ode"], "solve", "basic",
      "求解初值问题 $y'+y=0,\\ y(0)=1$。",
      "$y=e^{-x}$",
      "通解 $y=Ce^{-x}$，代入 $y(0)=1$ 得 $C=1$，故 $y=e^{-x}$。"),
]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
doc = {"questions": Q, "seq": len(Q),
       "_说明": "大学数学种子题库（线性代数20+数学分析21/22，挂接知识图谱KP）。字段：id 稳定编号 / subject / kp_ids(首个为主考查点) / type(choice|fill|solve) / difficulty(basic|mid|hard) / stem($..$LaTeX) / options / answer / solution(解析) / score"}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
by_sub = {}
for x in Q:
    by_sub[x["subject"]] = by_sub.get(x["subject"], 0) + 1
print("seeded:", len(Q), "题 →", OUT, "|", by_sub)
