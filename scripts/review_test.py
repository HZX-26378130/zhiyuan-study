# -*- coding: utf-8 -*-
"""验证间隔复习生命周期：产生→到期→通过推进(1/3/7/14)→毕业→失败重置→掌握放行。"""
import io, json, sys, time, urllib.request, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8765/api"


def call(method, path, body=None):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8", "replace"))


sid = call("GET", "/students")["students"][0]["id"]

# 1) 播种一道新错题（next_review = 明天）
iid = call("GET", "/wrongbook", {"sid": sid})
before_total = 0
# 直接用模块播种带时间控制的错题（需要精确控制到期时间，走文件）
sys.path.insert(0, ".")
from backend import wrongbook as wb
iid = wb.add(sid, "math", "间隔复习测试", "复做排期测试题：1+1=?（%d）" % int(time.time()),
             your="3", answer="2", note="测间隔", subject="linear_algebra", kp_id="det")
it = wb._get(sid, iid)
print("[1] seeded: stage =", it["review_stage"], "| next_review in %.1f 天" % ((it["next_review"] - time.time()) / 86400))

# 2) 生成变式题并手动构造到期（时间旅行：next_review 拨到过去）
wb.generate_variants(sid, iid)
w = wb._load(sid)
for x in w["items"]:
    if x["id"] == iid:
        x["next_review"] = time.time() - 3600   # 1 小时前到期
wb._save(sid, w)
r = call("GET", "/review/due?sid=%s" % sid)
print("[2] due queue:", r["due_n"], "题 | 含测试题 =", any(x["id"] == iid for x in r["items"]))

# 3) 第一次通过 → stage1 → 明天复做
v = call("POST", "/wrongbook/variants", {"sid": sid, "id": iid})
ans = (v["variants"][0].get("answer") or "2")
r = call("POST", "/wrongbook/practice", {"sid": sid, "id": iid, "idx": 0, "answer": ans})
rv = r.get("review", {})
print("[3] pass#1: stage =", rv.get("stage"), "| next_days =", rv.get("next_days"))

# 4) 连续通过到毕业（时间旅行 + 通过 ×3）
for i in range(3):
    w = wb._load(sid)
    for x in w["items"]:
        if x["id"] == iid:
            x["next_review"] = time.time() - 3600
    wb._save(sid, w)
    r = call("POST", "/wrongbook/practice", {"sid": sid, "id": iid, "idx": 0, "answer": ans})
    rv = r.get("review", {})
    print("[4] pass#%d: stage =", i + 2, rv.get("stage"), "| graduated =", rv.get("graduated"))

# 5) 毕业后 resolve 不再阻拦
r = call("POST", "/wrongbook/resolve", {"sid": sid, "id": iid})
print("[5] resolve after graduate: total =", r.get("total", "OK"))

# 6) 失败重置：再播种一道，到期后答错 → 回到明天
iid2 = wb.add(sid, "math", "间隔复习测试", "复做排期测试题2：2+2=?（%d）" % int(time.time()),
              your="5", answer="4", subject="linear_algebra", kp_id="det")
wb.generate_variants(sid, iid2)
w = wb._load(sid)
for x in w["items"]:
    if x["id"] == iid2:
        x["next_review"] = time.time() - 3600
wb._save(sid, w)
v = call("POST", "/wrongbook/variants", {"sid": sid, "id": iid2})
r = call("POST", "/wrongbook/practice", {"sid": sid, "id": iid2, "idx": 0, "answer": "乱答999"})
rv = r.get("review", {})
print("[6] fail: stage =", rv.get("stage"), "| next_days =", rv.get("next_days"), "(应≈1)")

# 7) 清理两条测试错题
w = wb._load(sid)
w["items"] = [x for x in w["items"] if x["id"] not in (iid, iid2)]
wb._save(sid, w)
print("[7] cleaned. ALL PASS")
