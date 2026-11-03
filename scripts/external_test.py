# -*- coding: utf-8 -*-
"""验证外部AI引导：提示词生成 → 回答收纳 → 归档可查 → 删除。"""
import io, json, sys, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8765/api"


def call(method, path, body=None, raw=False):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            b = r.read().decode("utf-8")
            return json.loads(b) if not raw else b
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", "replace"))


sid = call("GET", "/students")["students"][0]["id"]

# 1) 生成提示词
r = call("POST", "/external/prompt", {"sid": sid, "question": "线性方程组什么时候无解、什么时候有无穷多解？",
                                      "subject": "linear_algebra", "mode": "guide"})
print("[1] prompt gen: kp =", r.get("kp_name"), "| len =", len(r.get("prompt", "")))
p = r.get("prompt", "")
print("    片段:", p[:120].replace("\n", "⏎"))
assert "引导模式" in p and "变式" in p, "提示词应含四步法与引导规则"

# 2) 提交外部回答（模拟一段 DeepSeek 风格的引导式回答）
answer = ("【考点】线性方程组解的判定——系数矩阵与增广矩阵的秩。\n"
          "【引导】我们先从矩阵的秩说起：你先算一下系数矩阵 A 的秩 r(A)，再算增广矩阵 [A|b] 的秩 r([A|b])，"
          "比较这两个数。想想：如果 r(A) < r([A|b])，说明多出来的方程带来了什么矛盾？\n"
          "【反问】如果两个秩相等且等于未知数个数 n，解空间还有几个自由变量？\n"
          "【要点】r(A)=r([A|b])=n 唯一解；=r<n 无穷多解；r(A)<r([A|b]) 无解。\n"
          "【追问】齐次方程组的基础解系所含向量个数和秩有什么关系？")
r = call("POST", "/external/save", {"sid": sid, "question": "线性方程组什么时候无解、什么时候有无穷多解？",
                                    "subject": "linear_algebra", "answer": answer, "model": "DeepSeek网页版"})
print("[2] save: id =", r.get("id"), "| kp =", r.get("kp_name"), "| tldr =", (r.get("tldr") or "")[:60])
print("    quality =", r.get("quality"), "| note =", (r.get("quality_note") or "")[:60])
print("    key_points =", len(r.get("key_points") or []), "| followup =", (r.get("followup") or "")[:50])
iid = r["id"]

# 3) 收纳册列表 + 详情
r = call("GET", "/external", {"sid": sid})
print("[3] list: total =", r["total"], "| disclaimer =", ("阉割版" in r.get("disclaimer", "")), "| refs =", len(r.get("references", [])))
r = call("GET", "/external/item?sid=%s&id=%s" % (sid, iid), raw=True)
d = json.loads(r)
print("[4] detail: answer len =", len(d.get("answer", "")), "| style =", d.get("style"))

# 4) 删除
r = call("DELETE", "/external/item", {"sid": sid, "id": iid})
print("[5] delete: total =", r.get("total"))

print("ALL PASS")
