# -*- coding: utf-8 -*-
"""云端模式全链路验证：注册 → 登录 → 鉴权访问 → 数据落库 → 数据隔离。"""
import io, json, sys, urllib.request, urllib.error, uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8766/api"


def call(method, path, body=None, token=None):
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def main():
    uname = "测试同学" + uuid.uuid4().hex[:4]
    # 1) 注册
    s, r = call("POST", "/auth/register", {"name": uname, "password": "pass123456"})
    print("[1] register:", s, "| uid =", r.get("uid"), "| name =", r.get("name"))
    tok = r["token"]
    uid = r["uid"]

    # 2) 无 token 应 401
    s, r = call("GET", "/dashboard?sid=x")
    print("[2] no-token dashboard:", s, "|", r.get("error", "")[:30])

    # 3) 带 token 访问自己的档案（sid 强制为 uid）
    s, r = call("GET", "/dashboard", token=tok)
    print("[3] dashboard:", s, "| name =", (r.get("summary") or {}).get("name"), "| kp_count =", (r.get("summary") or {}).get("kp_count"))

    # 4) 问答一次（走云端 AI，数据应写 PG）
    s, r = call("POST", "/qa", {"question": "什么是行列式？", "subject": "linear_algebra", "use_web": False}, token=tok)
    print("[4] qa:", s, "| offline =", r.get("offline"), "| kp =", r.get("kp_name"))

    # 5) 再读 dashboard：掌握度应有记录
    s, r = call("GET", "/dashboard", token=tok)
    print("[5] dashboard after qa: kp_count =", (r.get("summary") or {}).get("kp_count"),
          "| qa =", (r.get("summary") or {}).get("stats", {}).get("qa"))

    # 6) 伪造他人 sid：应被强制改写为自己的 uid（读不到别人数据）
    s, r = call("GET", "/dashboard?sid=50bd69c440be", token=tok)
    print("[6] fake-sid dashboard:", s, "| name =", (r.get("summary") or {}).get("name"))

    # 7) 登录回环
    s, r = call("POST", "/auth/login", {"name": uname, "password": "pass123456"})
    print("[7] login:", s, "| uid match =", r.get("uid") == uid)
    s, r = call("POST", "/auth/login", {"name": uname, "password": "wrongpass"})
    print("[8] wrong password:", s, "|", r.get("error", "")[:20])

    # 8) 学生列表（云端=只有自己）
    s, r = call("GET", "/students", token=tok)
    st = r.get("students", [])
    print("[9] students:", s, "| count =", len(st), "| [0].id == uid =", bool(st) and st[0]["id"] == uid)

    # 9) 周报（云端数据聚合）
    s, r = call("GET", "/weekly", token=tok)
    print("[10] weekly:", s, "| offline =", r.get("offline"), "| report len =", len(r.get("report", "")))


if __name__ == "__main__":
    main()
