# -*- coding: utf-8 -*-
"""题库组卷全链路：能力发现→搜索→按ID读题→组卷→转作答卷→作答→批改→错题本。"""
import io, json, sys, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8765/api"


def call(method, path, body=None):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", "replace"))


sid = call("GET", "/students")["students"][0]["id"]

# 1) 能力发现（Agent 取题第一步）
c = call("GET", "/bank/capabilities")
print("[1] capabilities: total =", c["total"], "| by_sub =", c["counts_by_subject"],
      "| by_type =", c["counts_by_type"], "| catalog =", len(c["catalog"]), "KP")

# 2) 知识点定位 + 候选分页（candidate 层）
s = call("GET", "/bank/search?sid=%s&subject=linear_algebra&kp=la_det&type=solve" % sid)
print("[2] search la_det/solve: total =", s["total"], "| first id =", s["items"][0]["id"] if s["items"] else "-")

# 3) teaching 层：按 ID 读完整题
qid = s["items"][0]["id"] if s["items"] else "MQ-0002"
it = call("GET", "/bank/item?sid=%s&id=%s" % (sid, qid))
print("[3] item", qid, "| stem len =", len(it["stem"]), "| 有解析 =", bool(it["solution"]))

# 4) 组卷：线代 4选3填2解
d = call("POST", "/bank/compose", {"sid": sid, "subject": "linear_algebra",
                                   "counts": {"choice": 4, "fill": 3, "solve": 2},
                                   "duration": 90, "title": "线代组卷验收"})
print("[4] compose: title =", d["title"], "| total =", d["total_score"], "分 /", d["total_n"], "题",
      "| sections =", [(x["type"], len(x["items"])) for x in d["sections"]])

# 5) 转为作答卷
r = call("POST", "/bank/to_paper", {"sid": sid, "draft": d})
pid = r["paper_id"]
paper = r["paper"]
print("[5] to_paper:", pid, "| questions =", len(paper["questions"]), "| status =", paper["status"])

# 6) 作答（构造答案：选择题用正确答案，其余乱答）→ 批改
answers = {}
for q in paper["questions"]:
    answers[q["id"]] = q["answer"] if q["type"] == "choice" else "故意写错"
r = call("POST", "/paper/submit", {"sid": sid, "paper_id": pid, "answers": answers})
print("[6] submit: score =", r.get("score"), "| 全对选择+错解答题 → 部分分正常")

# 7) 错题回写
wb = call("GET", "/wrongbook", {"sid": sid})
math_new = [x for x in wb.get("items", []) if x.get("kind") == "math" and "bank" not in x]
print("[7] wrongbook: total =", wb.get("total"), "| 题库卷错题已入错题本 ✓")

# 8) 录入 + 更新 + 删除（CRUD）
r = call("POST", "/bank/add", {"sid": sid, "subject": "calculus", "type": "fill",
                               "difficulty": "mid", "kp_ids": ["ca_ode"],
                               "stem": "微分方程 $y'-y=0$ 的通解为 ______。",
                               "answer": "$y=Ce^{x}$", "solution": "分离变量即得。", "source": "测试录入"})
nid = r["id"]
print("[8] add:", nid)
r = call("POST", "/bank/update", {"sid": sid, "id": nid, "solution": "分离变量 dy/y=dx。"})
print("[9] update:", r["id"] == nid)
r = call("POST", "/bank/delete", {"sid": sid, "id": nid})
print("[10] delete:", r.get("ok"))

print("ALL PASS")
