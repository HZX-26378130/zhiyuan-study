# -*- coding: utf-8 -*-
"""验证 /api/qa/stream：统计 SSE 事件序列与增量。"""
import io, json, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sid = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/students", timeout=10).read())["students"][0]["id"]
body = json.dumps({"sid": sid, "question": "什么是特征值和特征向量？", "subject": "linear_algebra", "use_web": False}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8765/api/qa/stream", data=body, method="POST")
req.add_header("Content-Type", "application/json")
t0 = time.time()
deltas = []
final = None
first_delta_ts = None
with urllib.request.urlopen(req, timeout=180) as r:
    print("[status]", r.status, r.headers.get("Content-Type"))
    buf = b""
    while True:
        chunk = r.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            frame, buf = buf.split(b"\n\n", 1)
            ev, data = "", ""
            for line in frame.decode("utf-8", "replace").split("\n"):
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].strip()
            if not data:
                continue
            j = json.loads(data)
            if ev == "delta":
                if first_delta_ts is None:
                    first_delta_ts = time.time() - t0
                deltas.append(j["t"])
            elif ev == "final":
                final = j
print("[1] deltas =", len(deltas), "| 首增量延迟 = %.2fs" % (first_delta_ts or -1), "| 总耗时 %.2fs" % (time.time() - t0))
print("[2] 前120字直播内容:", "".join(deltas)[:120].replace("\n", "⏎"))
if final:
    r2 = final
    print("[3] final: kp =", r2.get("kp_name"), "| guidance =", len(r2.get("guidance", [])),
          "| counter =", len(r2.get("counter_questions", [])), "| expl len =", len(r2.get("explanation", "")),
          "| key_points =", len(r2.get("key_points", [])), "| followups =", len(r2.get("followups", [])),
          "| offline =", r2.get("offline"))
    print("[4] guidance[0]:", (r2.get("guidance") or ["(无)"])[0][:80])
else:
    print("[3] NO final event!")
