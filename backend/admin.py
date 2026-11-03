# -*- coding: utf-8 -*-
"""管理端聚合：用户数、调用数、反馈数，以及「长期该关注什么」。

设计原则：
- 只读：不修改任何学生数据，纯统计
- 只依赖 store 的公开函数 + 指标文件，不引入新的存储
- 规模假设：一个班 ~百人级别，全量扫描 JSON 完全够用（单次 <100ms）

给管理端的三类视图：
    overview()    一眼看全局的 KPI
    daily()       按天趋势（调用/反馈/问答），画图用
    users()       每个用户一行（用量、掌握度、薄弱点、最后活跃）
    weak_top()    全班共性薄弱点（教学上最该补的地方）
    longterm()    长期总结：规则聚合 + 可选 AI 叙述
"""
import os
import time

from . import knowledge, memory, metrics, points, store, wrongbook


def _day(ts):
    return time.strftime('%Y-%m-%d', time.localtime(ts or 0))


# 英语类考点用的是内部 id（不在五科图谱里），展示时给个像样的中文名
_FRIENDLY = {
    'en_vocab_cet4': '四六级词汇',
    'en_vocab_cet6': '六级词汇',
    'en_writing': '英语作文',
    'en_translation': '英语翻译',
    'english': '英语',
}


def _kp_label(subject, kp_id, name=None):
    if name and name != kp_id:      # 占位名等于 id 时不算真名字
        return name
    kp = knowledge.get_kp(subject, kp_id) if subject else None
    if kp and kp.get('name'):
        return kp['name']
    if kp_id in _FRIENDLY:
        return _FRIENDLY[kp_id]
    if subject in _FRIENDLY:
        return _FRIENDLY[subject]
    return kp_id


def _last_active(sid):
    """从 history.jsonl 取最后一次行为时间。"""
    try:
        h = store.get_history(sid, limit=1)
        if h:
            return h[0].get('ts') or 0
    except Exception:  # noqa: BLE001
        pass
    return 0


def _profiles():
    """遍历所有账号的档案摘要。"""
    out = []
    idx = store.list_students() or {}
    seen = set()
    for sid, info in idx.items():
        p = store.get_profile(sid) or {}
        if not p:
            continue
        seen.add(sid)
        out.append((sid, info.get('name') or p.get('name') or sid, p))
    # 自托管账号模式下注册用户可能不在 students.json
    for u in (store.users_all() or []):
        sid = u.get('uid')
        if not sid or sid in seen:
            continue
        p = store.get_profile(sid) or {}
        if p:
            seen.add(sid)
            out.append((sid, u.get('name') or p.get('name') or sid, p))
    return out


def overview():
    profiles = _profiles()
    now = time.time()
    active_7d = active_30d = 0
    content = {'qa': 0, 'graded': 0, 'quiz': 0, 'papers': 0, 'notes': 0,
               'wrongbook': 0, 'points_total': 0, 'feedback': 0, 'strategy': 0}
    for sid, _name, p in profiles:
        la = _last_active(sid)
        if la and now - la < 7 * 86400:
            active_7d += 1
        if la and now - la < 30 * 86400:
            active_30d += 1
        st = p.get('stats') or {}
        content['qa'] += int(st.get('qa') or 0)
        content['graded'] += int(st.get('graded') or 0)
        content['quiz'] += int(st.get('quiz_done') or 0)
        content['papers'] += int(st.get('papers_done') or 0)
        content['notes'] += int(st.get('notes') or 0)
        try:
            content['wrongbook'] += len((wrongbook._load(sid) or {}).get('items') or [])
        except Exception:  # noqa: BLE001
            pass
        try:
            content['points_total'] += int(points.balance(points.load(sid)) or 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            m = memory.get_memory(sid) or {}
            content['feedback'] += len(m.get('feedback') or [])
            if m.get('strategy'):
                content['strategy'] += 1
        except Exception:  # noqa: BLE001
            pass

    return {
        'users': len(profiles),
        'active_7d': active_7d,
        'active_30d': active_30d,
        'llm': metrics.llm_totals(30),
        'feedback': metrics.feedback_totals(30),
        'content': content,
        'channels': metrics.llm_by_channel(30),
        'generated_at': int(now),
    }


def daily(days=30):
    """按天合并三条序列：模型调用、反馈、问答次数。"""
    llm = {x['day']: x for x in metrics.llm_series(days)}
    fb = {x['day']: x for x in metrics.feedback_series(days)}
    since = time.time() - days * 86400
    qa = {}
    for sid, _name, p in _profiles():
        try:
            for h in (store.get_history(sid, limit=500) or []):
                ts = h.get('ts') or 0
                if ts < since:
                    continue
                if h.get('type') == 'qa':
                    d = _day(ts)
                    qa[d] = qa.get(d, 0) + 1
        except Exception:  # noqa: BLE001
            continue
    days_all = sorted(set(llm) | set(fb) | set(qa))
    out = []
    for d in days_all:
        l = llm.get(d) or {}
        f = fb.get(d) or {}
        out.append({
            'day': d,
            'llm_calls': l.get('calls', 0),
            'llm_fail': l.get('fail', 0),
            'llm_ms_avg': l.get('ms_avg', 0),
            'feedback_up': f.get('up', 0),
            'feedback_down': f.get('down', 0),
            'qa': qa.get(d, 0),
        })
    return out


def users(limit=200):
    rows = []
    by_user = {x['sid']: x for x in metrics.llm_by_user(365, limit=1000)}
    for sid, name, p in _profiles():
        st = p.get('stats') or {}
        mastery = p.get('mastery') or {}
        weak = [k for k, v in mastery.items() if (v.get('score') or 50) < 40]
        scores = [v.get('score') or 50 for v in mastery.values()]
        u = by_user.get(sid) or {}
        fb = 0
        try:
            fb = len((memory.get_memory(sid) or {}).get('feedback') or [])
        except Exception:  # noqa: BLE001
            pass
        rows.append({
            'sid': sid,
            'name': name,
            'created': p.get('created_at') or 0,
            'last_active': _last_active(sid),
            'qa': int(st.get('qa') or 0),
            'graded': int(st.get('graded') or 0),
            'quiz': int(st.get('quiz_done') or 0),
            'papers': int(st.get('papers_done') or 0),
            'notes': int(st.get('notes') or 0),
            'feedback': fb,
            'llm_calls': u.get('calls', 0),
            'llm_fail': u.get('fail', 0),
            'kp_count': len(mastery),
            'avg_score': round(sum(scores) / len(scores), 1) if scores else None,
            'weak_count': len(weak),
        })
    rows.sort(key=lambda r: -(r['last_active'] or r['created'] or 0))
    return rows[:limit]


def weak_top(limit=15):
    """全班共性薄弱点：按「多少人的掌握度低于 40」排序。"""
    agg = {}
    for sid, _name, p in _profiles():
        for kp_id, rec in (p.get('mastery') or {}).items():
            score = rec.get('score') or 50
            if score >= 60:
                continue
            a = agg.setdefault(kp_id, {'kp_id': kp_id, 'subject': rec.get('subject') or '',
                                       'name': kp_id, 'students': 0, 'score_sum': 0,
                                       'wrong': 0})
            a['students'] += 1
            a['score_sum'] += score
            a['wrong'] += int(rec.get('wrong') or 0)
    for a in agg.values():
        a['name'] = _kp_label(a['subject'], a['kp_id'], a.get('name'))
        a['avg_score'] = round(a['score_sum'] / a['students'], 1) if a['students'] else 0
        a.pop('score_sum', None)
    out = sorted(agg.values(), key=lambda x: (-x['students'], x['avg_score']))
    return out[:limit]


def channels():
    return metrics.llm_by_channel(30)


def longterm():
    """长期总结：规则聚合（不依赖 AI，随时可看）+ 可选的 AI 叙述。"""
    ov = overview()
    weak = weak_top(8)
    rows = users()
    active = [r for r in rows if r['last_active'] and time.time() - r['last_active'] < 7 * 86400]
    content = ov['content']
    llm = ov['llm']

    lines = []
    lines.append('**规模**：%d 位学员，近 7 天活跃 %d 人（%.0f%%），近 30 天活跃 %d 人。'
                 % (ov['users'], ov['active_7d'],
                    (ov['active_7d'] * 100.0 / ov['users']) if ov['users'] else 0,
                    ov['active_30d']))
    lines.append('**AI 使用**：近 30 天调用 %d 次（今天 %d 次），成功率 %.1f%%，平均耗时 %.0f ms。'
                 % (llm['calls'], llm['today'], llm['ok_rate'], llm['ms_avg']))
    if llm['fail']:
        lines.append('**失败**：%d 次调用失败，主要来自通道降级/限流，建议检查「通道」页的失败率。' % llm['fail'])
    lines.append('**学习行为**：问答 %d 次、批改 %d 次、词汇测验 %d 次、诊断卷 %d 套、讲义 %d 份。'
                 % (content['qa'], content['graded'], content['quiz'],
                    content['papers'], content['notes']))
    lines.append('**错题与积分**：错题本累计 %d 题，积分发放合计 %d 分。'
                 % (content['wrongbook'], content['points_total']))
    fb = ov['feedback']
    if fb['total']:
        lines.append('**反馈**：%d 条（👍 %d / 👎 %d，正向率 %.1f%%），%d 位学员已有个人策略卡。'
                     % (fb['total'], fb['up'], fb['down'], fb['positive_rate'] or 0,
                        content['strategy']))
    else:
        lines.append('**反馈**：暂无 👍/👎 记录，建议引导学生在回答下方评价，系统会据此生成教学策略。')

    if weak:
        top = '、'.join('%s（%d 人薄弱，均分 %.0f）' % (w['name'], w['students'], w['avg_score'])
                       for w in weak[:5])
        lines.append('**全班最该补的考点**：%s。' % top)
        lines.append('**建议**：优先为这几个考点生成讲义 + 诊断卷；对薄弱人数最多的 2 个考点做一次集中讲解。')
    else:
        lines.append('**薄弱点**：还没有足够数据（需要学生做过诊断卷/问答），先引导他们各做一次诊断卷。')

    slow = [r for r in rows if r['llm_fail'] > 0][:3]
    if slow:
        lines.append('**需要关注的学生**：%s —— 调用失败较多，可能是自己的 API Key 失效或网络问题。'
                     % '、'.join(r['name'] for r in slow))
    idle = [r for r in rows if r['created'] and not r['last_active']][:5]
    if idle:
        lines.append('**长期未活跃**：%s —— 可单独提醒一次。' % '、'.join(r['name'] for r in idle))

    return {
        'generated_at': int(time.time()),
        'text': '\n\n'.join(lines),
        'stats': {
            'users': ov['users'], 'active_7d': ov['active_7d'],
            'llm_30d': llm['calls'], 'feedback_30d': fb['total'],
            'weak_top': [w['name'] for w in weak[:5]],
        },
    }


def ai_summary():
    """让模型把上面的统计数据写成一段连贯的教学复盘（失败则回退规则版）。"""
    from . import llm
    base = longterm()
    if not llm.available():
        return {'ok': False, 'text': base['text'], 'detail': '未配置大模型，返回规则版总结'}
    prompt = (
        '你是教学管理者。下面是一个班级在学习系统里的使用数据，请写一份 200-400 字的中文复盘：\n'
        '1) 学习投入与趋势 2) 共性问题 3) 下学期/下一阶段三条具体建议。\n'
        '不要罗列数字，要点出「为什么」和「怎么做」。\n\n'
        '【统计数据】\n' + base['text']
    )
    try:
        out = llm.chat([
            {'role': 'system', 'content': '你是严谨的教学管理者，只基于给定数据说话，不编造。'},
            {'role': 'user', 'content': prompt},
        ], temperature=0.4, max_tokens=1200)
        return {'ok': True, 'text': (out or '').strip() or base['text'],
                'rule_based': base['text']}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'text': base['text'], 'detail': 'AI 生成失败：%s' % e}
