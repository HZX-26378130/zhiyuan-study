# -*- coding: utf-8 -*-
"""错题本：自动归纳批改/测验中的错题。
- 数学：诊断卷错题按知识点归类
- 英语：批改发现的错误按类型归类（语法/用词/搭配…）
- 词汇：测验答错的单词
反复出错的条目 count 累加（权重上升），可标记"已掌握"。
变式重练闭环：AI 针对错题生成同考点变式题，重练通过后才允许标记掌握。"""
import hashlib
import re
import time
import uuid

from . import store

MAX = 400
# 间隔复习（SM-2 简化）：变式重练通过后按阶段推迟下次复做时间；做错重置
REVIEW_INTERVALS = [86400, 3 * 86400, 7 * 86400, 14 * 86400]   # 通过 1/2/3/4 次后的间隔
GRADUATE_STAGE = 4


def _decorate_review(it, now=None):
    """懒迁移 + 计算 overdue（不落盘，读取时补字段）。"""
    now = now or time.time()
    it.setdefault('review_stage', 0)
    if not it.get('next_review'):
        it['next_review'] = it.get('ts', now) + REVIEW_INTERVALS[0]
    if it.get('resolved'):
        it['overdue'] = False
    else:
        it['overdue'] = it['next_review'] <= now
    return it


def _path(sid):
    return store._path(sid, 'wrongbook.json')


def _load(sid):
    return store._read_json(_path(sid), {'items': []})


def _save(sid, w):
    store._write_json(_path(sid), w)


def _key(kind, category, stem):
    return hashlib.md5((kind + '|' + category + '|' + stem[:80]).encode('utf-8')).hexdigest()


def add(sid, kind, category, stem, your='', answer='', note='', subject='', ref='', kp_id=''):
    w = _load(sid)
    k = _key(kind, category, stem)
    for it in w['items']:
        if it.get('key') == k and not it.get('resolved'):
            it['count'] = it.get('count', 1) + 1
            it['last'] = time.time()
            _save(sid, w)
            return it['id']
    it = {'id': uuid.uuid4().hex[:12], 'key': k, 'kind': kind, 'category': str(category)[:30],
          'stem': str(stem)[:300], 'your': str(your)[:300], 'answer': str(answer)[:800],
          'note': str(note)[:400], 'subject': subject, 'ref': str(ref)[:30], 'kp_id': kp_id[:40],
          'ts': time.time(), 'last': time.time(), 'count': 1, 'resolved': False,
          'variants': [], 'variants_ts': 0, 'practice': [],
          'review_stage': 0, 'next_review': time.time() + REVIEW_INTERVALS[0]}
    w['items'].append(it)
    w['items'] = w['items'][-MAX:]
    _save(sid, w)
    store.log_event(sid, 'wrongbook', {'kind': kind, 'category': str(category)[:30]})
    return it['id']


def _get(sid, iid):
    for it in _load(sid)['items']:
        if it['id'] == iid:
            return it
    return None


def _norm(s):
    """答案归一化：去空白/标点、全角转半角、统一大小写与常用乘除号。"""
    if s is None:
        return ''
    s = str(s)
    table = str.maketrans('０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ（）',
                          '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz()')
    s = s.translate(table)
    s = s.replace('×', '*').replace('÷', '/').replace('√', 'sqrt')
    s = re.sub(r'[\s，。、；：？！?!.,:;"\'「」【】（）()]+', '', s)
    return s.lower()


def _match(user, expected):
    a, b = _norm(user), _norm(expected)
    if not b:
        return None  # 无标准答案，无法自动判
    if not a:
        return False
    if a == b:
        return True
    try:
        if abs(float(a) - float(b)) < 1e-6:
            return True
    except ValueError:
        pass
    # 选择题式或短语式：互相包含即算对（长答案不适用）
    if len(b) <= 12 and b in a:
        return True
    if len(a) <= 12 and a in b:
        return True
    return False


def generate_variants(sid, iid):
    """为错题生成 2~3 道同考点变式题（AI；离线退化为知识图谱例题），结果缓存 3 天。"""
    from . import llm, knowledge
    w = _load(sid)
    it = next((x for x in w['items'] if x['id'] == iid), None)
    if not it:
        raise ValueError('错题不存在')
    if it.get('variants') and time.time() - it.get('variants_ts', 0) < 86400 * 3:
        return it['variants']

    variants = []
    subject = it.get('subject') or ''
    kp = knowledge.get_kp(subject, it['kp_id']) if subject and it.get('kp_id') else None
    kp_name = kp['name'] if kp else it.get('category', '')
    if llm.available():
        try:
            data = llm.chat_json([
                {'role': 'system', 'content': '你是出题助手。基于学生的错题，出2道考查同一知识点的变式题：数字/情境要变，考点不变，难度相当。'},
                {'role': 'user', 'content': '知识点：%s\n原错题：%s\n学生答案：%s\n正确答案：%s\n错因提示：%s\n\n'
                                            '输出JSON：{"questions":[{"q":"变式题干","answer":"简短标准答案","note":"一句话点拨"}]}' % (
                                                kp_name, it['stem'], it.get('your', ''), it.get('answer', ''), it.get('note', '')[:100])},
            ], temperature=0.7, max_tokens=1500)
        except llm.LLMError:          # 模型不可用 → 退到知识图谱例题
            data = None
        if data and isinstance(data.get('questions'), list):
            for q in data['questions'][:3]:
                if isinstance(q, dict) and q.get('q'):
                    variants.append({'q': str(q['q'])[:400],
                                     'answer': str(q.get('answer', ''))[:200],
                                     'note': str(q.get('note', ''))[:200]})
    if not variants and kp and kp.get('samples'):
        variants = [{'q': s['q'], 'answer': '', 'note': '参考解法：' + s['a'][:200], 'offline': True}
                    for s in kp['samples'][1:3]]
    if variants:
        it['variants'] = variants
        it['variants_ts'] = time.time()
        _save(sid, w)
    return variants


def submit_practice(sid, iid, idx, answer, self_correct=None):
    """提交变式题作答。expected 为空时接受自评（self_correct）。返回 {correct, feedback, expected}。"""
    from . import llm
    w = _load(sid)
    it = next((x for x in w['items'] if x['id'] == iid), None)
    if not it:
        raise ValueError('错题不存在')
    vs = it.get('variants') or []
    if idx < 0 or idx >= len(vs):
        raise ValueError('变式题序号无效')
    v = vs[idx]
    correct = _match(answer, v.get('answer', ''))
    feedback = ''
    if correct is None:
        correct = bool(self_correct)
        feedback = v.get('note', '')
    else:
        if correct:
            feedback = '回答正确。' + (v.get('note', '') or '')
        elif llm.available():
            try:
                data = llm.chat_json([
                    {'role': 'system', 'content': '你是阅卷老师。判断学生答案是否与标准答案等价（表达不同但意思/数值等价也算对）。'},
                    {'role': 'user', 'content': '题目：%s\n标准答案：%s\n学生答案：%s\n\n'
                                                '输出JSON：{"correct": true/false, "feedback": "一两句话点评，指出对在哪或错在哪"}' % (
                                                    v.get('q', ''), v.get('answer', ''), str(answer)[:200])},
                ], temperature=0.2, max_tokens=500)
            except llm.LLMError:      # 模型不可用 → 保留本地判分结果
                data = None
            if data and 'correct' in data:
                correct = bool(data['correct'])
                feedback = str(data.get('feedback', ''))[:300]
            if not feedback:
                feedback = ('判定正确' if correct else '参考答案：%s' % v.get('answer', ''))
        else:
            feedback = '标准答案：%s' % v.get('answer', '')
    it.setdefault('practice', []).append({'ts': time.time(), 'idx': idx, 'correct': bool(correct)})
    # 间隔复习调度：通过 → 推进阶段并推迟下次复做；做错 → 重置为明天
    stage = it.get('review_stage', 0)
    if correct:
        stage += 1
        it['review_stage'] = stage
        graduated = stage >= GRADUATE_STAGE
        it['review_graduated'] = graduated
        it['next_review'] = None if graduated else time.time() + REVIEW_INTERVALS[stage - 1]
    else:
        it['review_stage'] = 0
        it['next_review'] = time.time() + REVIEW_INTERVALS[0]
        it['review_graduated'] = False
    review_info = {'stage': it['review_stage'],
                   'next_days': round(max(0, (it.get('next_review') or 0) - time.time()) / 86400, 1)
                   if it.get('next_review') else None,
                   'graduated': bool(it.get('review_graduated'))}
    _save(sid, w)
    return {'correct': bool(correct), 'feedback': feedback,
            'expected': (v.get('answer', '') if correct else ''), 'total': len(vs),
            'review': review_info}


def practiced_ok(sid, iid):
    """该错题是否已通过变式重练（任一次答对即可），或间隔复习已毕业。"""
    it = _get(sid, iid)
    if not it:
        return True
    return it.get('review_graduated') or any(p.get('correct') for p in (it.get('practice') or []))


def due_review(sid, limit=6):
    """今日到期复习队列（含跨天轻微过期的），仪表盘与错题本用。"""
    now = time.time()
    w = _load(sid)
    from . import knowledge
    out = []
    for it in w['items']:
        if it.get('resolved'):
            continue
        _decorate_review(it, now)
        if it['overdue']:
            kp = knowledge.get_kp(it.get('subject', ''), it.get('kp_id', '')) or {}
            out.append({'id': it['id'], 'kind': it['kind'], 'category': it['category'],
                        'stem': it['stem'][:80],
                        'kp_name': kp.get('name', '') or it['category'],
                        'stage': it['review_stage'],
                        'due_days_ago': round((now - it['next_review']) / 86400, 1)})
    out.sort(key=lambda x: -x['due_days_ago'])
    return {'due_n': len(out), 'items': out[:limit]}


def _next_review_label(it):
    if it.get('resolved') or not it.get('next_review'):
        return ''
    days = (it['next_review'] - time.time()) / 86400
    if days <= 0:
        return '📅 到期'
    return '📅 %d 天后复做' % max(1, round(days))


def resolve(sid, iid, resolved=True, force=False):
    """标记掌握。需先通过变式重练（做对过一次）；force=True 可跳过。返回 (n, reason)。"""
    w = _load(sid)
    n = 0
    reason = ''
    for it in w['items']:
        if it['id'] == iid:
            if resolved and not force and not practiced_ok(sid, iid):
                reason = '请先完成「AI变式重练」并答对，再标记掌握'
                continue
            it['resolved'] = bool(resolved)
            n += 1
    if n:
        _save(sid, w)
    return n, reason


def grouped(sid):
    w = _load(sid)
    items = [x for x in w['items'] if not x.get('resolved')]
    now = time.time()
    for x in items:
        _decorate_review(x, now)
        x['review_label'] = _next_review_label(x)
    items.sort(key=lambda x: (not x['overdue'], -x.get('count', 1), -x['ts']))   # 到期优先
    due_n = sum(1 for x in items if x['overdue'])
    by_cat, by_kind = {}, {}
    for it in items:
        by_cat[it['category']] = by_cat.get(it['category'], 0) + 1
        by_kind[it['kind']] = by_kind.get(it['kind'], 0) + 1
    return {'items': items[:150], 'total': len(items), 'due_n': due_n,
            'byCategory': sorted(by_cat.items(), key=lambda x: -x[1]), 'byKind': by_kind}
