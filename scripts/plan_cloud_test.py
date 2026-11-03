# -*- coding: utf-8 -*-
"""云模式（8766）学习计划验证。"""
import io, json, sys, urllib.request, uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
B = "http://127.0.0.1:8766/api"


def call(m, p, b=None, t=None):
    d = json.dumps(b or {}).encode() if b is not None else None
    q = urllib.request.Request(B + p, data=d, method=m)
    q.add_header("Content-Type", "application/json")
    if t:
        q.add_header("Authorization", "Bearer " + t)
    return json.loads(urllib.request.urlopen(q, timeout=240).read())


r = call("POST", "/auth/register", {"name": "计划同学" + uuid.uuid4().hex[:3], "password": "pass123456"})
tok = r["token"]
print("[reg]", r["uid"][:8])

r = call("POST", "/plan/create", {"subject": "c_lang", "goal": "期末不挂科",
                                  "daily_minutes": 60, "level": "zero"}, t=tok)
P = r["plan"]
print("[create] days =", P["total_n"], "| D1 =", P["days"][0]["title"][:34])

r = call("POST", "/plan/done", {"day": 1}, t=tok)
print("[done] awarded =", r["awarded"], "| done_n =", r["plan"]["done_n"])

r = call("GET", "/dashboard", t=tok)
print("[dash] plan today =", ((r.get("plan") or {}).get("today_title") or "")[:34])
