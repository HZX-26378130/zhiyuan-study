# -*- coding: utf-8 -*-
import io, json, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
body = json.dumps({"name": "调试同学D4", "password": "pass123456"}).encode()
req = urllib.request.Request("http://127.0.0.1:8766/api/auth/register", data=body, method="POST")
req.add_header("Content-Type", "application/json")
t0 = time.time()
try:
    print(urllib.request.urlopen(req, timeout=40).read()[:120], "%.1fs" % (time.time() - t0))
except Exception as e:
    print("EXC %.1fs" % (time.time() - t0), repr(e)[:90])
