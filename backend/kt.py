# -*- coding: utf-8 -*-
"""贝叶斯知识追踪（BKT）：把「掌握度」从拍脑袋加减分升级为概率模型。

为什么换：
    原来掌握度是「对 +6 / 错 -6」的累加，问题很明显 ——
    连对 3 次就 68 分，但模型并不知道这个考点是不是本来就容易猜对；
    一次失手掉 6 分，也不区分「粗心」和「真不会」。

BKT 用四个参数描述一次作答：
    p_init   初始掌握概率
    p_learn  每次作答后"学会了"的转移概率
    p_slip   已掌握但答错的概率（手滑）
    p_guess  未掌握但蒙对的概率
每次作答做一次贝叶斯后验更新 + 一次学习转移，得到新的 p(know) ∈ (0,1)，
掌握度 = p(know) × 100。

纯标准库、无第三方依赖；参数可在 config.json 的 kt 段覆盖。
"""
import os

DEFAULT_PARAMS = {
    'p_init': 0.30,
    'p_learn': 0.15,
    'p_slip': 0.10,
    'p_guess': 0.20,
}

_FLOOR, _CEIL = 0.01, 0.99


def params():
    """允许在 config.json 的 {"kt": {...}} 里覆盖默认参数。"""
    p = dict(DEFAULT_PARAMS)
    try:
        # 延迟导入，避免 store/llm 循环依赖
        from . import llm
        cfg = llm.load_config() or {}
        override = cfg.get('kt') or {}
        for k in DEFAULT_PARAMS:
            v = override.get(k)
            if isinstance(v, (int, float)) and 0 < float(v) < 1:
                p[k] = float(v)
    except Exception:  # noqa: BLE001
        pass
    return p


def new_state(subject=''):
    return {'p': float(params()['p_init']), 'n': 0, 'wrong': 0, 'subject': subject}


def observe(state, correct, prm=None):
    """一次作答后的新状态。返回新 dict（不修改入参）。

    correct=True  → 后验上调（但要扣掉"蒙对"的可能）
    correct=False → 后验下调（但要扣掉"手滑"的可能）
    之后叠加学习转移：即使这次不会，也可能因为看了解析而学会了。
    """
    prm = prm or params()
    st = dict(state or new_state())
    p = float(st.get('p', prm['p_init']))
    slip, guess, learn = prm['p_slip'], prm['p_guess'], prm['p_learn']

    if correct:
        num = p * (1.0 - slip)
        den = num + (1.0 - p) * guess
    else:
        num = p * slip
        den = num + (1.0 - p) * (1.0 - guess)

    post = (num / den) if den > 0 else p
    nxt = post + (1.0 - post) * learn            # 学习转移
    st['p'] = min(_CEIL, max(_FLOOR, nxt))
    st['n'] = int(st.get('n', 0)) + 1
    if not correct:
        st['wrong'] = int(st.get('wrong', 0)) + 1
    return st


def score(state):
    """掌握度分数（0-100）。"""
    p = float((state or {}).get('p', DEFAULT_PARAMS['p_init']))
    return int(round(min(1.0, max(0.0, p)) * 100))


def level(score_value):
    if score_value is None:
        return '未诊断'
    if score_value < 40:
        return '薄弱'
    if score_value < 70:
        return '一般'
    return '良好'


def should_review(state, threshold=0.6):
    """是否建议再练一次（掌握概率低于阈值且练过至少一次）。"""
    st = state or {}
    return int(st.get('n', 0)) > 0 and float(st.get('p', 0)) < threshold
