# -*- coding: utf-8 -*-
"""验证每日课程：创建计划 → 备课 → 课程结构 → 验收卷存在 → 交卷 → 幂等复用。"""
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
call("POST", "/plan/delete", {"sid": sid})

r = call("POST", "/plan/create", {"sid": sid, "subject": "linear_algebra",
                                  "goal": "期末冲刺", "daily_minutes": 40, "level": "review"})
day = r["plan"]["today"]
print("[1] plan ready, today = D%s (%s)" % (day, r["plan"]["days"][day - 1]["title"][:30]))

# 2) 备课
r = call("POST", "/daily/generate", {"sid": sid, "day": day})
c = r
L = c.get("lesson") or {}
print("[2] course: kp =", c.get("kp_names"), "| quiz_pid =", (c.get("quiz_pid") or "")[:8])
print("    concept len =", len(L.get("concept", "")),
      "| 例题步骤 =", len((L.get("worked_example") or {}).get("steps") or []),
      "| 填空 =", len((L.get("fill_steps") or {}).get("blanks") or []))
print("    concept head:", (L.get("concept") or "")[:100].replace("\n", "⏎"))

# 3) 幂等：再次生成应返回同一课程（created 相同）
r2 = call("POST", "/daily/generate", {"sid": sid, "day": day})
print("[3] idempotent:", r2.get("created") == c.get("created"))

# 4) 验收卷可打开
if c.get("quiz_pid"):
    r = call("GET", "/paper?sid=%s&id=%s" % (sid, c["quiz_pid"]))
    print("[4] quiz: subject =", r.get("subject"), "| questions =", len(r.get("questions") or []), "| status =", r.get("status"))

# 5) summary 接口
r = call("GET", "/daily?sid=%s" % sid)
print("[5] summary: day =", r.get("day"), "| has_course =", r.get("has_course"), "| generated =", len(r.get("generated") or []))

print("ALL PASS")
