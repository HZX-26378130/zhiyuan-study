# -*- coding: utf-8 -*-
"""验证全班反馈学习闭环（对 8766 云模式实例）。"""
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
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def main():
    # 两个同学注册
    toks = []
    for n in ("学习同学甲" + uuid.uuid4().hex[:3], "学习同学乙" + uuid.uuid4().hex[:3]):
        s, r = call("POST", "/auth/register", {"name": n, "password": "pass123456"})
        toks.append(r["token"])
        print("[reg] %s → uid=%s" % (n[:8], r["uid"][:8]))

    # 甲问答一次（产生掌握度数据）
    s, r = call("POST", "/qa", {"question": "什么是行列式？", "subject": "linear_algebra", "use_web": False}, token=toks[0])
    print("[qa] %s offline=%s kp=%s" % (s, r.get("offline"), (r.get("kp_name") or "")[:12]))

    # 两人各提交反馈（差评带诉求 + 好评）
    s, r = call("POST", "/feedback", {"module": "qa", "target": "行列式", "rating": -1,
                                      "comment": "讲解太长，希望更短更直白"}, token=toks[0])
    print("[fb1]", s, r)
    s, r = call("POST", "/feedback", {"module": "paper", "target": "诊断卷", "rating": 1,
                                      "comment": "难度合适"}, token=toks[1])
    print("[fb2]", s, r)

    # 乙也问答一次
    s, r = call("POST", "/qa", {"question": "什么是矩阵的秩？", "subject": "linear_algebra", "use_web": False}, token=toks[1])
    print("[qa2] %s kp=%s" % (s, (r.get("kp_name") or "")[:12]))

    # 全员洞察
    s, r = call("GET", "/system/insight", token=toks[0])
    live = r.get("live", {})
    print("[insight] %s users=%s feedback_n=%s neg=%s weak=%s" % (
        s, live.get("users"), live.get("feedback_n"),
        len(live.get("neg_feedback") or []), len(live.get("weak_top") or [])))

    # 触发全局反思（AI 提炼策略）
    s, r = call("POST", "/system/reflect", {}, token=toks[0])
    print("[reflect] %s | strategy len=%s | head=%s" % (s, len(r.get("strategy") or ""), (r.get("strategy") or "")[:100].replace("\n", "⏎")))

    # 手动编辑策略
    s, r = call("POST", "/system/strategy", {"text": "【测试】讲解保持三步以内，先直觉后证明。"}, token=toks[0])
    print("[strategy-edit] %s | %s" % (s, (r.get("strategy") or "")[:40]))

    # 再读 insight：strategy 应为编辑后的
    s, r = call("GET", "/system/insight", token=toks[1])
    print("[insight2] %s | strategy=%s" % (s, (r.get("strategy") or "")[:40]))


if __name__ == "__main__":
    main()
