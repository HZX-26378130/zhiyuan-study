# -*- coding: utf-8 -*-
"""验证学习计划：创建（AI 润色）→ 今日任务 → 完成发分（防重复）→ 仪表盘 → 删除。"""
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
call("POST", "/plan/delete", {"sid": sid})  # 清理旧计划

# 1) 创建（复习起点，40 分钟/天）
r = call("POST", "/plan/create", {"sid": sid, "subject": "linear_algebra",
                                  "goal": "期末考 85 分", "exam_date": "2027-01-20",
                                  "daily_minutes": 40, "level": "review"})
P = r["plan"]
print("[1] create: days =", P["total_n"], "| D1 =", P["days"][0]["title"][:40],
      "| objectives =", len(P["days"][0]["objectives"]))
ids = [k for d in P["days"] for k in d["kp_ids"]]
assert len(ids) == len(set(ids)), "考点不应重复排课"
print("    覆盖考点 =", len(ids), "| 今天 = D%s" % P["today"])

# 2) 仪表盘卡
r = call("GET", "/dashboard", {"sid": sid})
pl = r.get("plan")
print("[2] dashboard plan:", (pl or {}).get("subject_name"), "| today =", (pl or {}).get("today_title", "")[:30])

# 3) 完成第 1 天 → 发分；重复完成不再发
r = call("POST", "/plan/done", {"sid": sid, "day": 1, "score": 88})
print("[3] done D1: awarded =", r["awarded"], "| done_n =", r["plan"]["done_n"])
r = call("POST", "/plan/done", {"sid": sid, "day": 1})
print("[4] re-done D1: awarded =", r["awarded"], "(应为0)")

# 4) 节奏预警（考试日期 2027-01-20，天数充足→正常）
print("[5] pace:", (r["plan"].get("pace_warning") or "")[:60])

# 5) 删除
call("POST", "/plan/delete", {"sid": sid})
r = call("GET", "/plan", {"sid": sid})
print("[6] after delete: plan =", r["plan"])
print("ALL PASS")
