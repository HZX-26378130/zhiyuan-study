# -*- coding: utf-8 -*-
"""验证本轮新功能：错题变式闭环 / AI周报 / 数据备份。"""
import io, json, sys, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8765/api"

def call(method, path, body=None, raw=False):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=240) as r:
        b = r.read()
        return (r.headers, b) if raw else json.loads(b.decode("utf-8"))

def main():
    st = call("GET", "/students")
    sid = (st.get("students") or [{}])[0].get("id") or "demo"

    # 1) 错题本现状
    wb = call("GET", "/wrongbook", {"sid": sid})
    items = wb.get("items", [])
    print("[1] wrongbook total =", wb.get("total"))
    if not items:
        import sys as _s, time as _t
        _s.path.insert(0, ".")
        from backend import wrongbook as _wb
        _iid = _wb.add(sid, "math", "行列式",
                       "计算 2 阶行列式 |1 2; 3 4| 的值。（%d）" % _t.time(),
                       your="10", answer="-2", note="ad-bc=1*4-2*3=-2，注意是交叉相减",
                       subject="linear_algebra", kp_id="det")
        print("    （已播种测试错题", _iid, "）")
        wb = call("GET", "/wrongbook", {"sid": sid})
        items = wb.get("items", [])
    it = items[0]
    print("    首条:", it["id"], it["kind"], it["category"][:20], "| practice:", len(it.get("practice", [])), "| variants:", len(it.get("variants", [])))

    # 2) 掌握门槛：未重练时应被拒绝
    try:
        call("POST", "/wrongbook/resolve", {"sid": sid, "id": it["id"]})
        print("[2] resolve 未重练 → 意外成功（门槛未生效?）")
    except urllib.error.HTTPError as e:
        print("[2] resolve 未重练 →", e.code, json.loads(e.read().decode("utf-8")).get("error", "")[:40])

    # 3) AI 变式出题
    v = call("POST", "/wrongbook/variants", {"sid": sid, "id": it["id"]})
    vs = v.get("variants", [])
    print("[3] variants =", len(vs))
    for i, q in enumerate(vs):
        print("    V%d:" % (i + 1), q["q"][:60].replace("\n", " "), "| ans:", (q.get("answer") or "")[:20], "| offline:", q.get("offline", False))

    # 4) 重练提交（拿第一题，故意用错误答案再试正确路径）
    if vs:
        ans = vs[0].get("answer") or ""
        if ans:
            r1 = call("POST", "/wrongbook/practice", {"sid": sid, "id": it["id"], "idx": 0, "answer": "乱答不靠谱的答案"})
            print("[4a] 错误作答 → correct =", r1["correct"], "| fb:", r1["feedback"][:50])
            r2 = call("POST", "/wrongbook/practice", {"sid": sid, "id": it["id"], "idx": 0, "answer": ans})
            print("[4b] 标准作答 → correct =", r2["correct"], "| expected:", (r2.get("expected") or "")[:20])
        else:
            r = call("POST", "/wrongbook/practice", {"sid": sid, "id": it["id"], "idx": 0, "answer": "", "self_correct": True})
            print("[4] 自评提交 → correct =", r["correct"])

    # 5) 现在标记掌握应放行
    r = call("POST", "/wrongbook/resolve", {"sid": sid, "id": it["id"]})
    print("[5] resolve 重练后 → total =", r.get("total"))

    # 6) AI 周报
    w = call("GET", "/weekly?sid=" + sid)
    print("[6] weekly offline =", w.get("offline"), "| report len =", len(w.get("report", "")))
    print("    " + w["report"][:150].replace("\n", " ⏎ "))

    # 7) 数据备份 zip
    h, b = call("GET", "/backup?sid=" + sid, raw=True)
    print("[7] backup:", h.get("Content-Type"), h.get("Content-Disposition"), "bytes =", len(b), "| zip magic =", b[:2] == b"PK")

if __name__ == "__main__":
    main()
