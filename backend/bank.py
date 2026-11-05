# -*- coding: utf-8 -*-
"""本地化大学数学题库 + 智能组卷（参考 JudgePeach/math-question-bank 的设计：
稳定题目 ID、知识点主辅标注、分层候选/完整两级读取、只读 Agent 取题接口）。
题库为全局资源（data/bank/math_bank.json 随仓库分发种子题），本地与云端共用；
教师/同学可扩充，云端模式下扩充内容随容器临时盘（重部署回退到种子集）。
与诊断卷深度联动：组卷结果可一键转为可作答、可自动批改、错题自动进错题本的试卷。"""
import os
import random
import re
import threading
import time

from . import knowledge, store

BANK_PATH = os.path.join(store.DATA_DIR, 'bank', 'math_bank.json')
_lock = threading.Lock()

MATH_SUBJECTS = ('linear_algebra', 'calculus')
TYPES = {'choice': '选择题', 'fill': '填空题', 'solve': '解答题'}
DIFFS = {'basic': '基础', 'mid': '中等', 'hard': '较难', 'comp': '竞赛'}
GRADIENT = [('basic', 0.35), ('mid', 0.4), ('hard', 0.2), ('comp', 0.05)]


def _load():
    return store._read_json(BANK_PATH, {'questions': [], 'seq': 0})


def _save(d):
    store._write_json(BANK_PATH, d)


def _kp_names(subject, kp_ids):
    out = []
    for kid in kp_ids or []:
        kp = knowledge.get_kp(subject, kid) or {}
        out.append(kp.get('name', kid))
    return out


def _candidate(q, kps_map):
    stem = q.get('stem', '')
    return {'id': q['id'], 'subject': q['subject'], 'type': q['type'],
            'type_name': TYPES.get(q['type'], q['type']),
            'difficulty': q.get('difficulty', 'mid'), 'difficulty_name': DIFFS.get(q.get('difficulty', 'mid'), ''),
            'kp_ids': q.get('kp_ids', []), 'kp_names': [kps_map.get(k, k) for k in q.get('kp_ids', [])],
            'stem_excerpt': re.sub(r'\$[^$]*\$', '…', stem)[:80], 'score': q.get('score', 10)}


def _full(q, kps_map):
    d = dict(q)
    d['kp_names'] = [kps_map.get(k, k) for k in q.get('kp_ids', [])]
    d['type_name'] = TYPES.get(q['type'], q['type'])
    d['difficulty_name'] = DIFFS.get(q.get('difficulty', 'mid'), '')
    return d


def capabilities():
    """只读 Agent 接口第一步：发现题库能力（题型/难度/知识点目录/数量）。"""
    d = _load()
    qs = d.get('questions', [])
    kps_map = {}
    catalog = []
    for s in MATH_SUBJECTS:
        for kid, kp in (knowledge.get_subject(s) or {}).get('kps', {}).items():
            kps_map[kid] = kp['name']
            n = sum(1 for q in qs if q['subject'] == s and kid in q.get('kp_ids', []))
            catalog.append({'subject': s, 'id': kid, 'name': kp['name'], 'questions': n})
    return {
        'subjects': {s: knowledge.subjects().get(s, s) for s in MATH_SUBJECTS},
        'types': TYPES, 'difficulties': DIFFS,
        'total': len(qs),
        'counts_by_type': {t: sum(1 for q in qs if q['type'] == t) for t in TYPES},
        'counts_by_subject': {s: sum(1 for q in qs if q['subject'] == s) for s in MATH_SUBJECTS},
        'catalog': catalog,
        'agent_guide': ('只读取题流程：GET /api/bank/capabilities 发现能力 → /api/bank/search '
                        '按 subject/kp/type/difficulty/q 分页取候选（candidate）→ /api/bank/item?id= 读完整题目'
                        '（teaching，含解析）。检索结果需人工核对后再使用。'),
    }


def search(subject=None, kp=None, qtype=None, difficulty=None, q='', page=1, size=20):
    d = _load()
    kps_map = {kid: kp['name'] for s in MATH_SUBJECTS
               for kid, kp in (knowledge.get_subject(s) or {}).get('kps', {}).items()}
    items = []
    for x in d.get('questions', []):
        if subject and x['subject'] != subject:
            continue
        if qtype and x['type'] != qtype:
            continue
        if difficulty and x.get('difficulty') != difficulty:
            continue
        if kp and kp not in x.get('kp_ids', []):
            continue
        if q and q.lower() not in (x.get('stem', '') + x.get('answer', '') + x.get('solution', '')).lower():
            continue
        items.append(_candidate(x, kps_map))
    items.sort(key=lambda x: x['id'])
    page = max(1, int(page or 1))
    size = max(1, min(int(size or 20), 100))
    start = (page - 1) * size
    chunk = items[start:start + size]
    return {'total': len(items), 'page': page, 'size': size,
            'next_page': (page + 1) if start + size < len(items) else None,
            'truncated': False, 'items': chunk}


def get_item(qid):
    d = _load()
    kps_map = {kid: kp['name'] for s in MATH_SUBJECTS
               for kid, kp in (knowledge.get_subject(s) or {}).get('kps', {}).items()}
    for x in d.get('questions', []):
        if x['id'] == qid:
            return _full(x, kps_map)
    return None


def add(fields):
    subject = fields.get('subject', '')
    if subject not in MATH_SUBJECTS:
        raise ValueError('题库仅支持大学数学（线性代数/数学分析），后续扩展其他科目')
    qtype = fields.get('type', '')
    if qtype not in TYPES:
        raise ValueError('题型必须是 choice/fill/solve')
    stem = (fields.get('stem') or '').strip()
    if len(stem) < 6:
        raise ValueError('题干太短')
    answer = (fields.get('answer') or '').strip()
    if not answer:
        raise ValueError('答案不能为空')
    options = fields.get('options') or []
    if qtype == 'choice':
        if len(options) < 2:
            raise ValueError('选择题至少两个选项')
    kp_ids = [k for k in (fields.get('kp_ids') or []) if knowledge.get_kp(subject, k)][:6]
    with _lock:
        d = _load()
        d['seq'] = int(d.get('seq', 0)) + 1
        q = {'id': 'MQ-%04d' % d['seq'], 'subject': subject, 'kp_ids': kp_ids,
             'type': qtype, 'difficulty': fields.get('difficulty', 'mid') if fields.get('difficulty') in DIFFS else 'mid',
             'stem': stem[:2000],
             'options': [{'key': o.get('key', 'ABCD'[i]).upper()[:1], 'text': str(o.get('text', ''))[:500]}
                         for i, o in enumerate(options)][:6],
             'answer': answer[:800], 'solution': (fields.get('solution') or '')[:3000],
             'score': 10, 'source': (fields.get('source') or '教师录入')[:40],
             'created': time.time(), 'updated': time.time()}
        d.setdefault('questions', []).append(q)
        _save(d)
    return q['id']


def update(qid, fields):
    with _lock:
        d = _load()
        for q in d.get('questions', []):
            if q['id'] == qid:
                for k in ('stem', 'answer', 'solution', 'difficulty', 'source'):
                    if fields.get(k):
                        q[k] = str(fields[k])[:3000]
                if fields.get('kp_ids') is not None:
                    q['kp_ids'] = [k for k in fields['kp_ids'] if knowledge.get_kp(q['subject'], k)][:6]
                if fields.get('options'):
                    q['options'] = [{'key': o.get('key', 'ABCD'[i]).upper()[:1], 'text': str(o.get('text', ''))[:500]}
                                    for i, o in enumerate(fields['options'])][:6]
                q['updated'] = time.time()
                _save(d)
                return qid
    raise ValueError('题目不存在')


def delete(qid):
    with _lock:
        d = _load()
        before = len(d.get('questions', []))
        d['questions'] = [q for q in d['questions'] if q['id'] != qid]
        if len(d['questions']) == before:
            raise ValueError('题目不存在')
        _save(d)
    return True


def compose(subject, kp_ids=None, counts=None, duration=90, title='', seed=None):
    """智能组卷：按题型数量与难度梯度（基础40% 中等40% 较难20%）选题，每题 10 分。"""
    if subject not in MATH_SUBJECTS:
        raise ValueError('仅支持大学数学科目')
    counts = {t: int(counts.get(t, 0) if counts else 0) for t in TYPES}
    total_n = sum(counts.values())
    if total_n <= 0:
        raise ValueError('至少选择 1 道题')
    if total_n > 30:
        raise ValueError('单卷最多 30 题')
    d = _load()
    kps_map = {kid: kp['name'] for s in MATH_SUBJECTS
               for kid, kp in (knowledge.get_subject(s) or {}).get('kps', {}).items()}
    rng = random.Random(seed)
    sections, used = [], set()
    total_score = 0
    for qtype, want in TYPES.items():
        n = counts.get(qtype, 0)
        if n <= 0:
            continue
        pool = [q for q in d.get('questions', [])
                if q['subject'] == subject and q['type'] == qtype and q['id'] not in used
                and (not kp_ids or any(k in q.get('kp_ids', []) for k in kp_ids))]
        items = []
        buckets = {dk: [q for q in pool if q.get('difficulty', 'mid') == dk] for dk in DIFFS}
        for dk, ratio in GRADIENT:
            k = min(len(buckets[dk]), round(n * ratio) if n >= 3 else (n if dk == 'mid' else 0))
            pick = rng.sample(buckets[dk], k) if k else []
            for q in pick:
                used.add(q['id'])
                items.append({'qid': q['id'], 'score': 10, 'question': _full(q, kps_map)})
        # 不足时从剩余题池补齐
        rest = [q for q in pool if q['id'] not in used]
        rng.shuffle(rest)
        for q in rest[:n - len(items)]:
            used.add(q['id'])
            items.append({'qid': q['id'], 'score': 10, 'question': _full(q, kps_map)})
        if not items:
            continue
        total_score += 10 * len(items)
        notes = {'choice': '每小题 10 分，选出最符合题意的一项。',
                 'fill': '每小题 10 分，将答案填在题目指定的横线上。',
                 'solve': '每小题 10 分，写出必要的推演步骤。'}
        sections.append({'type': qtype, 'type_name': TYPES[qtype], 'items': items,
                         'note': notes[qtype]})
    if not sections:
        raise ValueError('筛选条件下没有可用题目——先去「题库浏览」录入，或放宽筛选')
    return {'title': (title or (knowledge.subjects().get(subject, subject) + ' 组卷练习'))[:60],
            'subject': subject, 'duration': max(15, min(int(duration or 90), 240)),
            'total_score': total_score, 'total_n': total_score // 10,
            'sections': sections, 'created': time.time()}


def to_paper(sid, draft):
    """把组卷草稿转为可作答、可自动批改的标准试卷（进入诊断卷列表与错题闭环）。"""
    from . import store as _st
    questions, idx = [], 0
    for sec in draft.get('sections', []):
        for it in sec.get('items', []):
            q = it['question']
            questions.append({'id': 'q%d' % idx, 'type': q['type'],
                              'kp_id': (q.get('kp_ids') or [''])[0],
                              'kp_name': (q.get('kp_names') or [''])[0],
                              'stem': q['stem'],
                              'options': q.get('options') or [],
                              'answer': q.get('answer', ''),
                              'analysis': q.get('solution', '')[:500],
                              'bank_id': q['id']})
            idx += 1
    if not questions:
        raise ValueError('草稿里没有题目')
    paper = {'id': _st.new_id(), 'subject': draft.get('subject', 'linear_algebra'),
             'created': time.time(), 'status': 'open', 'difficulty': 'bank',
             'title': draft.get('title', ''), 'duration': draft.get('duration', 90),
             'total_score': draft.get('total_score', 10 * len(questions)),
             'source': 'bank', 'questions': questions}
    _st.save_paper(sid, paper)
    _st.log_event(sid, 'paper', {'action': 'bank_compose', 'n': len(questions),
                                 'title': paper['title'][:40]})
    return paper
