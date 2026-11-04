# -*- coding: utf-8 -*-
"""AI 学习周报：聚合近 7 天行为流水（问答/测验/批改/积分/错题），生成一段总结与下周建议。
自我迭代机制的用户可见层：让"系统在观察你的学习"变成一段可读的报告。"""
import time

from . import llm, points, store, wrongbook


def metrics(sid):
    """近 7 天行为指标（不调 AI，纯统计，供前端展示与周报输入）。"""
    now = time.time()
    since = now - 7 * 86400
    evs = [e for e in store.get_history(sid, limit=800) if e.get('ts', 0) >= since]
    ev_by_type = {}
    for e in evs:
        ev_by_type[e.get('type', '?')] = ev_by_type.get(e.get('type', '?'), 0) + 1

    p = points.load(sid)
    earns = [e for e in p.get('earn', []) if e.get('t', 0) >= since]
    pts_by_cat = {}
    for e in earns:
        pts_by_cat[e.get('cat', '')] = pts_by_cat.get(e.get('cat', ''), 0) + e.get('pts', 0)

    w = wrongbook._load(sid)
    wrong_new = sum(1 for x in w['items'] if x.get('ts', 0) >= since)
    wrong_done = sum(1 for x in w['items'] if x.get('resolved') and x.get('last', 0) >= since)
    wrong_open = sum(1 for x in w['items'] if not x.get('resolved'))

    # 薄弱知识点（掌握分最低的前 5 个，名称从知识图谱查）
    from . import knowledge
    mastery = store.mastery_levels(sid) or {}
    weak = []
    for kpid, v in mastery.items():
        rec = v if isinstance(v, dict) else {}
        kp = knowledge.get_kp(rec.get('subject', ''), kpid) or {}
        weak.append({'kp': kp.get('name', kpid), 'level': rec.get('score', 50),
                     'subject': rec.get('subject', '')})
    weak.sort(key=lambda x: x['level'])
    weak = weak[:5]

    st = points.stats(p)
    return {'days': 7, 'events': ev_by_type, 'pointsWeek': sum(pts_by_cat.values()),
            'pointsByCat': pts_by_cat, 'wrongNew': wrong_new, 'wrongResolved': wrong_done,
            'wrongOpen': wrong_open, 'weakKps': weak, 'streak': st.get('streak', 0),
            'weekPts': st.get('week', 0), 'weekGoal': st.get('weekGoal', 0)}


def build(sid):
    """生成周报：AI 可用时调用大模型，否则拼接规则文案。返回 {report, metrics, offline}。"""
    m = metrics(sid)
    facts = ('近7天行为：' +
             '，'.join('%s×%d' % (k, v) for k, v in sorted(m['events'].items(), key=lambda x: -x[1])[:6]) +
             '；本周积分 %d/%s' % (m['weekPts'], m['weekGoal'] or '∞') +
             '；连续达标 %d 天' % m['streak'] +
             '；新增错题 %d，解决 %d，未解决 %d' % (m['wrongNew'], m['wrongResolved'], m['wrongOpen']) +
             '；薄弱点：' + ('、'.join('%s(%s)' % (x['kp'], x['level']) for x in m['weakKps']) or '暂无数据'))

    if llm.available():
        try:
            out = llm.chat([
                {'role': 'system', 'content': '你是学习督导顾问。请根据学生近 7 天的学习数据撰写一份简短周报：'
                                              '语气亲切、内容具体、建议可执行，全文不超过 200 字；'
                                              '结构为 ①本周亮点 ②薄弱信号 ③下周建议三条（编号）。避免空泛表述。'},
                {'role': 'user', 'content': facts},
            ], temperature=0.6, max_tokens=800)
            if out and out.strip():
                return {'report': out.strip(), 'metrics': m, 'offline': False}
        except llm.LLMError:
            pass

    lines = ['【本周亮点】', '· 行为记录：%s' % ('，'.join('%s %d 次' % (k, v) for k, v in sorted(m['events'].items(), key=lambda x: -x[1])[:4]) or '本周暂无学习记录'),
             '· 获得积分 %d，连续达标 %d 天' % (m['weekPts'], m['streak']),
             '', '【薄弱信号】',
             '· 新增错题 %d、未解决 %d；薄弱点：%s' % (m['wrongNew'], m['wrongOpen'], '、'.join(x['kp'] for x in m['weakKps']) or '暂无'),
             '', '【下周建议】',
             '1. 每天完成至少 1 次 AI 问答或词汇测验，保持连续达标。',
             '2. 打开错题本，对未解决错题做「AI变式重练」，答对后再标记掌握。',
             '3. 针对薄弱知识点生成一张诊断卷，检验掌握情况。']
    return {'report': '\n'.join(lines), 'metrics': m, 'offline': True}
