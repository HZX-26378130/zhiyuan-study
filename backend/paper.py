# -*- coding: utf-8 -*-
"""知识诊断卷：根据薄弱点画像 + 校本资料出诊断卷（数学：选择/填空/计算/证明；英语：词汇选择/翻译/写作），
交卷后自动批改（客观题精确判分，主观题 LLM 按标准评卷），结果回写薄弱点画像。"""
import random
import time

from . import english, knowledge, llm, materials, points, search, store, wrongbook

MATH_TYPES = ['choice', 'fill', 'compute', 'proof']


# ---------- 生成 ----------

def generate(sid, subject, kp_ids=None, difficulty='mid', counts=None):
    counts = counts or {}
    papers_dir_note = None
    if subject == 'english':
        return _gen_english(sid, counts)
    sub = knowledge.get_subject(subject)
    if not sub:
        return {'error': '未知科目'}
    if not kp_ids:
        kp_ids = knowledge.recommend_kps(sid, subject, n=int(counts.get('kps', 4)))
    kp_ids = [k for k in kp_ids if k in sub['kps']]
    if not kp_ids:
        return {'error': '未选择知识点'}

    kps_ctx = []
    for kid in kp_ids:
        kp = sub['kps'][kid]
        kps_ctx.append('【%s】%s\n要点：%s\n易错：%s\n前置：%s'
                       % (kp['name'], kp['description'][:100],
                          '；'.join(kp['key_points'][:4]),
                          '；'.join(kp['common_errors'][:2]),
                          '、'.join(kp.get('prereqs', [])) or '无'))
    mat_chunks = materials.retrieve(sid, ' '.join(sub['kps'][k]['name'] for k in kp_ids), top=2)
    mat_ctx = '\n'.join('【校本资料·%s】%s' % (c['material'], c['text'][:250]) for c in mat_chunks)

    n_choice = int(counts.get('choice', 3))
    n_fill = int(counts.get('fill', 2))
    n_solve = int(counts.get('solve', 2))
    questions = None
    if llm.available():
        questions = _llm_questions(subject, kps_ctx, mat_ctx, difficulty, n_choice, n_fill, n_solve)
    offline = questions is None
    if offline:
        questions = _offline_questions(subject, kp_ids, n_choice, n_fill, n_solve)

    paper = {
        'id': ('p%s' % time.time_ns())[-12:],
        'created': time.time(),
        'subject': subject,
        'subject_name': sub['name'],
        'kps': kp_ids,
        'kp_names': [sub['kps'][k]['name'] for k in kp_ids],
        'difficulty': difficulty,
        'status': 'open',
        'score': None,
        'offline': offline,
        'questions': questions,
    }
    store.save_paper(sid, paper)
    return _public_paper(paper)


def _gen_english(sid, counts):
    level = counts.get('level', 'cet4')
    n_vocab = int(counts.get('vocab', 6))
    questions = []
    # 词汇选择
    from . import vocab
    qz = vocab.quiz(sid, level=level, count=max(3, n_vocab))
    data_vocab = vocab.QUIZ_CACHE.pop(qz['quiz_id'], None)
    for q in (data_vocab or {}).get('items', []):
        questions.append({'id': 'v' + str(len(questions)), 'type': 'choice', 'kp_id': 'en_vocab_%s' % level,
                          'stem': '选择与 “%s” 词义相符的选项%s' % (q['word'], ('（语境：%s）' % q['sentence']) if q.get('sentence') else ''),
                          'options': q['options'], 'answer': q['answer'],
                          'analysis': '词义：%s%s' % (q['options'][0]['meaning'] if q['options'] else '', ('；例句：%s' % q['sentence']) if q.get('sentence') else '')})
    # 翻译
    items = english.list_translation_items(level)
    if items:
        t = english.get_translation_item(items[0]['id'])
        questions.append({'id': 't1', 'type': 'translation', 'kp_id': 'en_translation',
                          'stem': '将下面的段落翻译成英文：\n' + t['source_cn'],
                          'answer': t['reference_en'],
                          'analysis': '关键表达：' + '；'.join(t['key_points'])})
    # 写作
    prompts = english.list_prompts(level)
    if prompts:
        p = english.get_prompt(prompts[0]['id'])
        questions.append({'id': 'w1', 'type': 'writing', 'kp_id': 'en_writing',
                          'stem': p['directions'],
                          'answer': p['model_essay'],
                          'analysis': '；'.join(p['useful_expressions'][:3])})
    paper = {'id': ('p%s' % time.time_ns())[-12:], 'created': time.time(), 'subject': 'english',
             'subject_name': '大学英语（%s）' % level.upper(), 'kps': [], 'kp_names': ['词汇', '翻译', '写作'],
             'difficulty': level, 'status': 'open', 'score': None, 'offline': True, 'questions': questions}
    store.save_paper(sid, paper)
    return _public_paper(paper)


def _llm_questions(subject, kps_ctx, mat_ctx, difficulty, n_choice, n_fill, n_solve):
    diff_note = {'easy': '基础直接题', 'mid': '常规考试难度', 'hard': '含1-2道综合提升题'}[difficulty]
    user = '\n\n'.join(filter(None, [
        '基于以下知识点命制一份诊断卷（%s）。\n%s\n%s' % (diff_note, '\n\n'.join(kps_ctx),
                                                       ('优先贴合校本资料：\n' + mat_ctx) if mat_ctx else ''),
        '共出 %d 道单选题、%d 道填空题、%d 道解答题（计算或证明），覆盖上述知识点，标注每题对应知识点名。'
        % (n_choice, n_fill, n_solve),
        '输出 JSON：{"questions": [{"id": "q1..", "type": "choice|fill|solve", "kp": "知识点名", '
        '"stem": "题干（数学用Unicode记号，不要用LaTeX反斜杠）", "options": [{"key":"A","text":".."},..]（仅选择题）, '
        '"answer": "选择题填字母；填空/解答题给完整参考答案", "analysis": "解题步骤与易错提醒"}]}',
    ]))
    try:
        res = llm.chat_json([{'role': 'system', 'content': '你是资深的大学数学命题老师，题目严谨、答案准确、难度适中。'},
                             {'role': 'user', 'content': user}], temperature=0.5)
    except llm.LLMError:
        return None
    if not res or not res.get('questions'):
        return None
    out = []
    for i, q in enumerate(res['questions']):
        out.append({'id': q.get('id') or 'q%d' % i,
                    'type': q.get('type') if q.get('type') in ('choice', 'fill', 'solve') else 'solve',
                    'kp_id': '', 'kp_name': q.get('kp', ''),
                    'stem': q.get('stem', ''), 'options': q.get('options') if q.get('type') == 'choice' else None,
                    'answer': str(q.get('answer', '')), 'analysis': q.get('analysis', '')})
    return out


def _offline_questions(subject, kp_ids, n_choice, n_fill, n_solve):
    """离线出卷：计算/概念题取自内置例题库；选择题为"易错点辨认"（正确答案=该知识点的典型错误认识）。"""
    questions = []
    idx = 0
    kps = [knowledge.get_kp(subject, kid) for kid in kp_ids]
    kps = [k for k in kps if k]
    pool = []
    for kp in kps:
        for s in kp['samples']:
            pool.append((kp, s))
    random.shuffle(pool)
    for kp, s in [p for p in pool if p[1]['type'] == 'compute'][:n_solve]:
        questions.append({'id': 'q%d' % idx, 'type': 'solve', 'kp_id': kp['id'], 'kp_name': kp['name'],
                          'stem': s['q'], 'answer': s['a'], 'analysis': '对比要点：' + '；'.join(kp['key_points'][:2])})
        idx += 1
    for kp, s in [p for p in pool if p[1]['type'] == 'concept'][:n_fill]:
        questions.append({'id': 'q%d' % idx, 'type': 'fill', 'kp_id': kp['id'], 'kp_name': kp['name'],
                          'stem': s['q'] + '（简答）', 'answer': s['a'], 'analysis': '易错：' + '；'.join(kp['common_errors'][:2])})
        idx += 1
    # 选择题：每个知识点最多一道，正确答案=典型易错点，干扰项=其他知识点的正确要点
    sub_kps = list(knowledge.get_subject(subject)['kps'].values())
    used_kp = set()
    for kp, _s in pool:
        if len([q for q in questions if q['type'] == 'choice']) >= n_choice:
            break
        if kp['id'] in used_kp or not kp['common_errors'] or not kp['key_points']:
            continue
        used_kp.add(kp['id'])
        other = random.choice([k for k in sub_kps if k['id'] != kp['id'] and k['key_points']])
        texts = [kp['common_errors'][0], other['key_points'][0], kp['key_points'][0],
                 '以上三项均为该知识点的常见错误认识']
        random.shuffle(texts)
        options = [{'key': 'ABCD'[i], 'text': t} for i, t in enumerate(texts)]
        answer = next(o['key'] for o in options if o['text'] == kp['common_errors'][0])
        questions.append({'id': 'q%d' % idx, 'type': 'choice', 'kp_id': kp['id'], 'kp_name': kp['name'],
                          'stem': '关于「%s」，下列哪一项属于常见错误认识（易错点）？' % kp['name'],
                          'options': options, 'answer': answer,
                          'analysis': '易错点解析：%s 正确认识：%s' % (kp['common_errors'][0], kp['key_points'][0])})
        idx += 1
    return questions


def _public_paper(paper):
    return {k: v for k, v in paper.items() if k not in ('offline',)} | {
        'questions': [{k: v for k, v in q.items() if k != 'answer'} for q in paper['questions']],
        'offline': paper.get('offline', False),
    }


# ---------- 批改 ----------

def _norm_ans(a):
    return ''.join(str(a).split()).upper()


def _keyword_score(ans, ref):
    """主观题离线估分：参考答案关键词在学生答案中的命中率。"""
    import re
    keys = [k for k in re.findall(r'[\u4e00-\u9fff]{2,8}|[A-Za-z]{3,}|[0-9.]+', ref)]
    if not keys:
        return 0.5
    hits = sum(1 for k in keys if k in str(ans))
    return hits / len(keys)


def submit(sid, paper_id, answers):
    paper = store.get_paper(sid, paper_id)
    if not paper:
        return {'error': '试卷不存在'}
    if paper.get('status') == 'graded':
        return {'error': '该试卷已批改'}
    results = []
    total, got = 0, 0.0
    per_q = 10.0
    wrong_kps = []
    for q in paper['questions']:
        ans = (answers or {}).get(q['id'], '')
        total += per_q
        if q['type'] == 'choice':
            ok = _norm_ans(ans) == _norm_ans(q['answer'])
            score = per_q if ok else 0
            feedback = q.get('analysis', '')
            if not ok:
                feedback = '正确答案：%s。\n%s' % (q['answer'], q.get('analysis', ''))
        elif q['type'] == 'fill':
            ok = _norm_ans(ans) and _keyword_score(ans, q['answer']) >= 0.55
            score = per_q if ok else (per_q * 0.4 if ans else 0)
            feedback = ('答案要点一致。' if ok else '') + '参考答案：%s\n%s' % (q['answer'], q.get('analysis', ''))
        else:
            # 主观题：LLM 评卷优先
            score, feedback, ok = _grade_subjective(sid, q, ans, per_q)
        got += score
        if score < per_q * 0.6:
            wrong_kps.append(q.get('kp_id') or q.get('kp_name') or '')
        results.append({'id': q['id'], 'type': q['type'], 'stem': q['stem'][:80],
                        'your_answer': str(ans)[:500], 'score': round(score, 1),
                        'full': per_q, 'correct': score >= per_q * 0.6,
                        'answer': q['answer'], 'feedback': feedback})

    paper['status'] = 'graded'
    paper['graded_at'] = time.time()
    paper['score'] = round(got, 1)
    paper['results'] = results
    paper['report'] = _build_report(sid, paper, results)
    store.save_paper(sid, paper)

    # 回写掌握度 + 错题自动归入错题本
    subj = paper['subject']
    for q in paper['questions']:
        r = next((x for x in results if x['id'] == q['id']), None)
        if not r:
            continue
        kid = q.get('kp_id')
        if kid:
            delta = +6 if r['correct'] else -6
            store.update_mastery(sid, kid, subj if subj != 'english' else 'english', delta, wrong=not r['correct'])
        if not r['correct']:
            wrongbook.add(sid, 'math', q.get('kp_name') or '综合', stem=q['stem'],
                          your=r['your_answer'], answer=q['answer'], note=r['feedback'][:350],
                          subject=subj, ref=paper_id, kp_id=kid or '')
    prof = store.get_profile(sid)
    prof['stats']['papers_done'] = prof.get('stats', {}).get('papers_done', 0) + 1
    store.save_profile(sid, prof)
    store.log_event(sid, 'paper_grade', {'paper_id': paper_id, 'score': paper['score'],
                                         'wrong_kps': [w for w in wrong_kps if w]})
    awarded = points.notify(sid, 'paper')
    # 答对的知识点：自动完成对应的薄弱点系统任务
    for q in paper['questions']:
        r = next((x for x in results if x['id'] == q['id']), None)
        if r and r['correct'] and q.get('kp_id'):
            awarded += points.notify_kp(sid, subj, q['kp_id'])
    weak = [w for w in wrong_kps if w]
    advice = ('建议针对薄弱知识点生成讲义复习，并再生成一份诊断卷验证。' if weak
              else '本轮掌握情况良好，可提升难度继续巩固。')
    return {'paper_id': paper_id, 'score': paper['score'], 'total': total,
            'pct': round(100 * got / max(1, total)), 'results': results,
            'awarded': awarded,
            'wrong_kps': weak, 'advice': advice,
            'next': {'generate_notes': bool(weak), 'kps': weak[:5]}}


def _build_report(sid, paper, results):
    """诊断精讲报告：每道错题配考点精讲、易错警示、同类例题、权威/开源资料。"""
    subj = paper['subject']
    report = []
    for q in paper['questions']:
        r = next((x for x in results if x['id'] == q['id']), None)
        if not r or r['correct']:
            continue
        kid = q.get('kp_id')
        kp = knowledge.get_kp(subj, kid) if kid else None
        kp_name = q.get('kp_name') or (kp['name'] if kp else '综合')
        entry = {
            'id': q['id'], 'type': q['type'], 'stem': q['stem'],
            'kp_name': kp_name,
            'your_answer': r['your_answer'], 'answer': q['answer'],
            'analysis': q.get('analysis', ''), 'feedback': r['feedback'],
            'key_points': kp['key_points'][:5] if kp else [],
            'common_errors': kp['common_errors'] if kp else [],
            'similar': [{'q': s['q'], 'a': s['a']} for s in (kp['samples'][:3] if kp else [])],
            'sources': [{'title': x['title'], 'note': x.get('url', '')} for x in (kp['refs'] if kp else [])],
        }
        # 开源题库/资料索引补充
        hits = search.match_sources(kp_name + ' ' + q['stem'][:40], top=2)
        entry['sources'] += [{'title': '📚 ' + h['name'], 'note': h['url']} for h in hits]
        # 校本资料相关片段
        if not kid or not kp:
            chunks = materials.retrieve(sid, q['stem'][:60], top=1)
            entry['material_refs'] = [{'material': c['material'], 'text': c['text'][:180]} for c in chunks]
        report.append(entry)
    return report


def _grade_subjective(sid, q, ans, per_q):
    if llm.available() and ans.strip():
        try:
            res = llm.chat_json([
                {'role': 'system', 'content': '你是大学数学阅卷老师，按步骤给分（满分10分），指出学生答案中的错误步骤与概念漏洞。'},
                {'role': 'user', 'content': '题目：%s\n参考答案：%s\n学生答案：%s\n'
                                            '输出 JSON：{"score": 0-10, "correct": true/false(得分≥6), "feedback": "逐步点评与纠错"}'
                                            % (q['stem'], q['answer'], ans)}], temperature=0.2)
            if res and isinstance(res.get('score'), (int, float)):
                return (float(res['score']), res.get('feedback', ''), bool(res.get('correct')))
        except llm.LLMError:
            pass
    if not ans.strip():
        return 0.0, '未作答。参考答案：%s' % q['answer'], False
    cov = _keyword_score(ans, q['answer'])
    score = round(per_q * min(1.0, max(0.2, cov)), 1)
    ok = score >= per_q * 0.6
    note = '' if llm.available() else '（离线模式按要点重合度估分，请对照参考答案自查）'
    return score, '要点覆盖率约 %d%%。%s\n参考答案：%s' % (cov * 100, note, q['answer']), ok
