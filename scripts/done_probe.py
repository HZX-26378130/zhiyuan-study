# -*- coding: utf-8 -*-
import io, json, sys, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
body = json.dumps({"sid": "50bd69c440be", "day": 2}).encode()
req = urllib.request.Request("http://127.0.0.1:8765/api/plan/done", data=body, method="POST")
req.add_header("Content-Type", "application/json")
try:
    print(urllib.request.urlopen(req, timeout=60).read().decode("utf-8")[:150])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode("utf-8")[:300])
