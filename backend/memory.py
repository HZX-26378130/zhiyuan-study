# -*- coding: utf-8 -*-
"""自我迭代记忆模块（agent 自学习闭环）：
偏好指令记忆 + 反馈事件积累 + 反思策略卡，注入后续所有教学提示词。
交互 → 反馈 → 记忆 → 策略更新 → 更优的下一轮。
全局层：聚合所有同学的问题与反馈 → 全局教学策略，全班共享（云端多人版核心学习回路）。"""
import threading
import time

from . import knowledge, llm, store


# ---------- 偏好指令（持久指令，注入提示词） ----------

def add_preference(sid, text):
    text = (text or '').strip()
    if not text:
        return False
    prof = store.get_profile(sid)
    if prof is None:
        return False
    prefs = prof['memory']['preferences']
    if text not in prefs:
        prefs.append(text)
        prefs = prefs[-50:]  # 上限50条，防止无限膨胀
        prof['memory']['preferences'] = prefs
        store.save_profile(sid, prof)
        store.log_event(sid, 'preference', {'text': text})
    return True


def remove_preference(sid, text):
    prof = store.get_profile(sid)
    prefs = prof['memory']['preferences']
    if text in prefs:
        prefs.remove(text)
        store.save_profile(sid, prof)
        return True
    return False


# ---------- 反馈事件 ----------

def add_feedback(sid, module, target, rating, comment=''):
    """rating: 1=有用 0=一般 -1=没帮助"""
    prof = store.get_profile(sid)
    if prof is None:
        return False
    fb = {'ts': time.time(), 'module': module, 'target': str(target)[:120],
          'rating': int(rating), 'comment': (comment or '').strip()[:500]}
    prof['memory']['feedback'].append(fb)
    prof['memory']['feedback'] = prof['memory']['feedback'][-200:]
    store.save_profile(sid, prof)
    store.log_event(sid, 'feedback', fb)
    return True


def update_feedback(sid, ts, rating=None, comment=None):
    """编辑已记录的反馈（可改评分/评论）。ts 为原反馈的时间戳。"""
    prof = store.get_profile(sid)
    if prof is None:
        return False
    for fb in prof['memory']['feedback']:
        if abs(fb['ts'] - float(ts)) < 0.001:
            if rating is not None:
                fb['rating'] = int(rating)
            if comment is not None:
                fb['comment'] = str(comment).strip()[:500]
            fb['edited'] = True
            store.save_profile(sid, prof)
            return True
    return False


def delete_feedback(sid, ts):
    prof = store.get_profile(sid)
    before = len(prof['memory']['feedback'])
    prof['memory']['feedback'] = [f for f in prof['memory']['feedback'] if abs(f['ts'] - float(ts)) >= 0.001]
    changed = len(prof['memory']['feedback']) < before
    if changed:
        store.save_profile(sid, prof)
    return changed


def set_strategy(sid, text):
    """手动编辑教学策略卡。"""
    prof = store.get_profile(sid)
    if prof is None:
        return False
    prof['memory']['strategy'] = (text or '').strip()[:3000]
    prof['memory']['strategy_updated'] = time.time()
    prof['memory']['strategy_manual'] = bool(text)
    store.save_profile(sid, prof)
    store.log_event(sid, 'reflect', {'strategy': prof['memory']['strategy'][:200], 'manual': True})
    return True


# ---------- 反思：更新教学策略卡 ----------

def _stats_digest(sid):
    """聚合近期错因与交互统计，作为反思输入。"""
    history = store.get_history(sid, limit=300)
    qa_topics, wrong_kps, essay_notes = [], [], []
    for rec in history:
        t = rec.get('type')
        if t == 'qa' and rec.get('kps'):
            qa_topics.extend(rec['kps'])
        if t == 'paper_grade':
            for q in rec.get('wrong_kps', []):
                wrong_kps.append(q)
        if t == 'english' and rec.get('summary'):
            essay_notes.append(rec['summary'][:150])
    m = store.mastery_levels(sid)
    low = sorted(m.items(), key=lambda x: x[1]['score'])[:8]
    return {
        'qa_topics': qa_topics[-20:],
        'wrong_kps': wrong_kps[-20:],
        'low_mastery': [{'id': k, 'score': v['score']} for k, v in low],
        'essay_notes': essay_notes[-5:],
    }


def reflect(sid):
    """复盘反馈与错因，生成/更新教学策略卡。配 LLM 时深度总结，离线时统计汇总。"""
    prof = store.get_profile(sid)
    if prof is None:
        return None
    digest = _stats_digest(sid)
    feedback = prof['memory']['feedback'][-40:]
    prefs = prof['memory']['preferences']

    strategy, new_prefs, extra = '', [], {}
    if llm.available():
        prompt = {
            'role': 'user',
            'content': (
                '你是一名教学系统的自我优化器。下面是一个学生的学习档案数据。'
                '请复盘：1) 学生多次反馈暴露出的教学问题；2) 反复出错的知识点与错因模式；'
                '3) 应该如何调整后续的讲解深度、出卷难度和讲义侧重。'
                '输出 JSON：{"strategy": "给后续AI教学的策略说明（300字内，具体可执行，含难度调整和讲解风格）", '
                '"new_preferences": ["从反馈中提炼出的学生显性偏好，每条一句话"], '
                '"focus_kps": ["最需要关注的知识点id"], "difficulty_adjust": "up|down|same"}\n\n'
                '偏好指令: %s\n反馈事件: %s\n学习统计: %s'
                % (prefs, feedback, digest)
            ),
        }
        try:
            res = llm.chat_json([prompt], temperature=0.3)
            if res:
                strategy = res.get('strategy', '')
                new_prefs = [p for p in res.get('new_preferences', []) if isinstance(p, str)][:10]
                extra = {'focus_kps': res.get('focus_kps', []),
                         'difficulty_adjust': res.get('difficulty_adjust', 'same')}
        except llm.LLMError as e:
            strategy = ''
            extra = {'error': str(e)}
    if not strategy:
        # 离线启发式反思
        neg = [f for f in feedback if f['rating'] < 0]
        pos = [f for f in feedback if f['rating'] > 0]
        lines = ['【离线统计反思】']
        lines.append('- 近期交互 %d 次，其中差评 %d 次、好评 %d 次。' % (len(feedback), len(neg), len(pos)))
        if digest['low_mastery']:
            lines.append('- 掌握度最低的知识点：' + '、'.join(
                '%s(%s)' % (x['id'], x['score']) for x in digest['low_mastery'][:5]))
        if digest['wrong_kps']:
            lines.append('- 错题集中知识点：' + '、'.join(sorted(set(digest['wrong_kps']))[:6]))
        if neg:
            lines.append('- 差评意见摘要：' + '；'.join(f['comment'][:40] for f in neg[:3] if f['comment']))
        lines.append('- 建议后续：出卷难度下调一档，讲解多给铺垫步骤，优先覆盖上述薄弱知识点。')
        strategy = '\n'.join(lines)

    prof['memory']['strategy'] = strategy
    prof['memory']['strategy_updated'] = time.time()
    for p in new_prefs:
        if p not in prof['memory']['preferences']:
            prof['memory']['preferences'].append(p)
    store.save_profile(sid, prof)
    store.log_event(sid, 'reflect', {'strategy': strategy[:200], **{k: v for k, v in extra.items() if k != 'error'}})
    return {'strategy': strategy, 'new_preferences': new_prefs, 'updated': prof['memory']['strategy_updated'], **extra}


# ---------- 注入教学提示词 ----------

def teaching_context(sid, max_prefs=8):
    """生成注入各模块提示词的个性化教学上下文。"""
    prof = store.get_profile(sid)
    if prof is None:
        return ''
    mem = prof['memory']
    parts = []
    if mem['preferences']:
        parts.append('学生对你的持久要求（必须遵守）：\n' +
                     '\n'.join('- ' + p for p in mem['preferences'][-max_prefs:]))
    if mem['strategy']:
        parts.append('你的教学策略卡（上一次自我反思的结论，遵循执行）：\n' + mem['strategy'])
    m = prof.get('mastery', {})
    low = sorted(m.items(), key=lambda x: x[1]['score'])[:5]
    if low:
        def _kp_label(k, rec):
            kp = knowledge.get_kp(rec.get('subject', ''), k) or {}
            return kp.get('name', k.replace('_', ' '))
        parts.append('学生当前最薄弱知识点（讲解时多铺垫、出题时优先）：' +
                     '、'.join('%s(%s分)' % (_kp_label(k, v), v['score']) for k, v in low))
    return '\n\n'.join(parts)


def get_memory(sid):
    prof = store.get_profile(sid)
    if prof is None:
        return None
    mem = prof['memory']
    return {
        'preferences': mem['preferences'],
        'strategy': mem['strategy'],
        'strategy_updated': mem['strategy_updated'],
        'feedback': mem['feedback'][-30:][::-1],
        'llm': llm.available(),
    }


# ---------- 全员反馈学习（系统级自我迭代） ----------

_SYSTEM_KEY = 'system/strategy.json'
_gctx_cache = {'data': None, 'ts': 0.0}
_refresh_lock = threading.Lock()


def _system_doc():
    return store._read_json(store._path(_SYSTEM_KEY), None)


def _write_system_doc(doc):
    store._write_json(store._path(_SYSTEM_KEY), doc)


def global_insight():
    """聚合全部同学：反馈、近期问题、掌握度 → 系统级洞察（无 AI，纯统计）。"""
    sids = store.all_sids()
    feedback, questions, mastery_sum = [], [], {}
    for sid in sids[-200:]:
        try:
            prof = store.get_profile(sid)
            if not prof:
                continue
            for f in (prof.get('memory', {}).get('feedback') or [])[-30:]:
                feedback.append({'name': prof.get('name', sid[:6]), 'rating': f.get('rating', 0),
                                 'comment': str(f.get('comment', ''))[:80], 'module': f.get('module', '')})
            for kpid, rec in (prof.get('mastery') or {}).items():
                if not isinstance(rec, dict):
                    continue
                key = (rec.get('subject', ''), kpid)
                s = mastery_sum.setdefault(key, {'score': 0.0, 'users': 0})
                s['score'] += rec.get('score', 50)
                s['users'] += 1
            hist = store.get_history(sid, limit=60)
            for rec in hist:
                if rec.get('type') == 'qa' and rec.get('q'):
                    questions.append({'name': prof.get('name', sid[:6]), 'q': str(rec['q'])[:80]})
        except (OSError, KeyError, ValueError):
            continue
    weak = sorted(
        ({'subject': s, 'id': k, 'score': round(v['score'] / max(v['users'], 1)),
          'users': v['users'], 'name': (knowledge.get_kp(s, k) or {}).get('name', k.replace('_', ' '))}
         for (s, k), v in mastery_sum.items() if v['users'] >= 1),
        key=lambda x: x['score'])[:8]
    return {'users': len(sids), 'feedback_n': len(feedback),
            'feedback_recent': feedback[-12:],
            'neg_feedback': [f for f in feedback if f.get('rating', 0) < 0][-8:],
            'weak_top': weak, 'questions_recent': questions[-15:]}


def reflect_system(force=False):
    """全班反馈学习：聚合所有人数据 → AI（或离线规则）提炼全局教学策略，全班共享。"""
    cur = _system_doc()
    if not force and cur and cur.get('text') and time.time() - cur.get('updated', 0) < 86400:
        return dict(cur, refreshed=False)
    ins = global_insight()
    strategy = ''
    if llm.available():
        try:
            res = llm.chat_json([
                {'role': 'user', 'content':
                    '你是教学系统的全局优化器。以下是全班同学（%d人）的汇总数据。'
                    '请提炼一份"全局教学策略"，供AI老师对每一位同学教学时遵守：'
                    '1) 同学们反馈中反复出现的教学问题与诉求；'
                    '2) 全班共性薄弱知识点及卡点模式；'
                    '3) 对讲解方式、例题选择、难度节奏的具体要求。'
                    '输出 JSON：{"strategy": "全局教学策略（250字内，具体可执行）", '
                    '"themes": ["高频问题主题3-5条"]}。\n\n'
                    '同学反馈: %s\n近期问题: %s\n全班掌握度: %s'
                    % (ins['users'], ins['feedback_recent'], ins['questions_recent'][:10],
                       [{'name': w['name'], 'avg': w['score'], 'users': w['users']} for w in ins['weak_top']])
                }], temperature=0.3, max_tokens=1200)
            if res and res.get('strategy'):
                strategy = str(res['strategy'])[:800]
        except llm.LLMError:
            strategy = ''
    if not strategy:
        lines = ['【全班数据自动汇总】']
        lines.append('- 覆盖 %d 位同学，累计反馈 %d 条。' % (ins['users'], ins['feedback_n']))
        if ins['neg_feedback']:
            lines.append('- 差评诉求（应优先改进）：' + '；'.join(
                (f['comment'] or f['module'])[:40] for f in ins['neg_feedback'][:4]))
        if ins['weak_top']:
            lines.append('- 全班共性薄弱点（讲解多铺垫、出题优先）：' + '、'.join(
                '%s(%d分/%d人)' % (w['name'], w['score'], w['users']) for w in ins['weak_top'][:5]))
        if ins['questions_recent']:
            lines.append('- 近期高频问题主题：' + '；'.join(
                q['q'][:30] for q in ins['questions_recent'][-4:]))
        strategy = '\n'.join(lines)
    doc = {'text': strategy, 'updated': time.time(),
           'insight': {'users': ins['users'], 'feedback_n': ins['feedback_n'],
                       'weak_top': ins['weak_top'][:5], 'hot_questions': ins['questions_recent'][-6:]}}
    _write_system_doc(doc)
    _gctx_cache['ts'] = 0.0
    return dict(doc, refreshed=True)


def global_context(max_len=1200):
    """注入问答提示词的全局教学上下文（全班共享，缓存10分钟）。"""
    now = time.time()
    if _gctx_cache['data'] is not None and now - _gctx_cache['ts'] < 600:
        return _gctx_cache['data']
    doc = _system_doc()
    data = ''
    if doc and doc.get('text'):
        data = ('【全班教学策略】（由全体同学的问题与反馈自动学习得出，请遵循）\n' + str(doc['text'])[:max_len])
        ins = doc.get('insight') or {}
        if ins.get('weak_top'):
            data += '\n全班共性薄弱点（多铺垫）：' + '、'.join(
                w.get('name', '') for w in ins['weak_top'][:5])
    _gctx_cache['data'] = data
    _gctx_cache['ts'] = now
    return data


def refresh_system_async(max_age=86400):
    """策略过期时后台刷新（反馈提交后触发，不阻塞请求）。"""
    doc = _system_doc()
    stale = not doc or not doc.get('text') or time.time() - doc.get('updated', 0) > max_age
    if not stale:
        return False
    if _refresh_lock.acquire(blocking=False):
        def _job():
            try:
                reflect_system(force=False)
            except Exception:
                pass
            finally:
                _refresh_lock.release()
        threading.Thread(target=_job, daemon=True).start()
        return True
    return False


def get_system():
    return _system_doc() or {'text': '', 'updated': None, 'insight': {}}


def set_system_strategy(text):
    """手动编辑全局策略（教师/管理员场景保留）。"""
    doc = _system_doc() or {}
    doc['text'] = (text or '').strip()[:2000]
    doc['updated'] = time.time()
    _write_system_doc(doc)
    _gctx_cache['ts'] = 0.0
    return doc
