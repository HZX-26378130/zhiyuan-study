# -*- coding: utf-8 -*-
"""每日课程（阶段二）：把"学习计划"的当天考点编成一节可自学的完整课程。
吸收 good-learning 四步法：概念讲解 → 完整例题（每步理由）→ 同构填步题 → 变式验收（复用诊断卷引擎）。
课程按天持久化，可回看；LLM 不可用时用知识图谱素材拼装离线课程。"""
import time

from . import knowledge, llm, paper, store

MAX_DAYS = 60


def _path(sid):
    return store._path(sid, 'daily.json')


def _load(sid):
    return store._read_json(_path(sid), {'courses': {}})


def _save(sid, d):
    store._write_json(_path(sid), d)


def list_days(sid):
    """已生成课程的天号列表（降序）。"""
    d = _load(sid)
    out = []
    for k, c in d.get('courses', {}).items():
        out.append({'day': int(k), 'title': c.get('title', ''), 'created': c.get('created')})
    return sorted(out, key=lambda x: -x['day'])[:MAX_DAYS]


def get(sid, day):
    return _load(sid).get('courses', {}).get(str(int(day)))


def _plan_day(sid, day):
    plan = store._read_json(store._path(sid, 'plan.json'), None)
    if not plan:
        raise ValueError('请先在「学习计划」创建逐日计划')
    d = next((x for x in plan['days'] if x['day'] == int(day)), None)
    if not d:
        raise ValueError('计划里没有 D%s' % day)
    return plan, d


def _offline_lesson(kp_ids, kps):
    """离线课程：知识图谱素材拼装。"""
    concept_parts, sample = [], None
    for k in kp_ids:
        kp = kps.get(k) or {}
        if not kp:
            continue
        concept_parts.append('### %s\n%s\n\n**要点：**\n%s' % (
            kp.get('name', k), kp.get('description', ''),
            '\n'.join('- ' + x for x in kp.get('key_points', [])[:3])))
        if not sample and kp.get('samples'):
            sample = kp['samples'][0]
    ex = sample or {'q': '（暂无例题，请去问答页让 AI 出一道）', 'a': ''}
    return {
        'concept': '\n\n'.join(concept_parts) or '（素材缺失）',
        'worked_example': {'q': ex.get('q', ''), 'steps': ['参考解法：' + ex.get('a', '')[:200]], 'answer': ex.get('a', '')[:200]},
        'fill_steps': {'q': '（离线模式无填步题，请直接做下方验收练习）', 'blanks': [], 'hint': ''},
        'recap': '回顾今天的考点，明天课程会把它们作为前置知识使用。',
    }


def generate(sid, day):
    """生成（或复用）当天的课程 + 验收练习卷。"""
    plan, d = _plan_day(sid, day)
    day = int(day)
    dset = _load(sid)
    course = dset.get('courses', {}).get(str(day))
    if course:
        return course

    subject = plan['subject']
    kp_ids = d.get('kp_ids') or []
    kps = (knowledge.get_subject(subject) or {}).get('kps') or {}
    kp_names = [kps[k]['name'] for k in kp_ids if k in kps]
    if not kp_names:
        raise ValueError('当天没有有效考点')

    # 1) 课程主体（一次 LLM 调用；离线回退）
    lesson = None
    if llm.available():
        ctx = []
        for k in kp_ids:
            kp = kps.get(k) or {}
            ctx.append('【%s】%s\n要点：%s\n示例：%s' % (
                kp.get('name', k), kp.get('description', '')[:150],
                '；'.join(kp.get('key_points', [])[:3]),
                (kp.get('samples') or [{}])[0].get('q', '')[:120]))
        try:
            res = llm.chat_json([
                {'role': 'user', 'content':
                    '你是大学课程的授课教师，请为当日课程备制完整讲义。科目：%s；今日考点：%s；学生薄弱点：%s。\n\n'
                    '参考资料：\n%s\n\n'
                    '请按四步法输出 JSON：\n'
                    '{"concept": "概念讲解，markdown 格式，每个考点一段，依次包含直观引入、定义与适用条件、最小示例，全节 350-600 字，公式使用 $...$", '
                    '"worked_example": {"q": "一道覆盖全部考点的完整例题题干", '
                    '"steps": ["步骤 1：做法。理由：说明选择该步骤的依据", "……每一步均须包含做法与依据"], "answer": "最终答案"}, '
                    '"blanks": ["按出现顺序的答案"], "hint": "一句提示"}, '
                    '"recap": "混合回顾：说明本节内容与前后知识的联系（1-2 句）"}'
                    % (knowledge.subjects().get(subject, subject), '、'.join(kp_names),
                       '、'.join(w['name'] for w in (memory_weak_top(sid) or [])[:3]) or '（未知）',
                       '\n'.join(ctx))
                }], temperature=0.4, max_tokens=3500)
            if res and res.get('worked_example'):
                lesson = {
                    'concept': str(res.get('concept', ''))[:4000],
                    'worked_example': {
                        'q': str((res.get('worked_example') or {}).get('q', ''))[:500],
                        'steps': [str(s)[:300] for s in (res.get('worked_example') or {}).get('steps', [])][:8],
                        'answer': str((res.get('worked_example') or {}).get('answer', ''))[:300],
                    },
                    'fill_steps': {
                        'q': str((res.get('fill_steps') or {}).get('q', ''))[:600],
                        'blanks': [str(b)[:60] for b in (res.get('fill_steps') or {}).get('blanks', [])][:4],
                        'hint': str((res.get('fill_steps') or {}).get('hint', ''))[:150],
                    },
                    'recap': str(res.get('recap', ''))[:300],
                }
        except llm.LLMError:
            lesson = None
    if not lesson:
        lesson = _offline_lesson(kp_ids, kps)

    # 2) 变式验收卷（复用诊断卷引擎，4 题）
    quiz_pid = ''
    try:
        p = paper.generate(sid, subject, kp_ids=kp_ids, difficulty='mid', counts={'choice': 2, 'fill': 1, 'solve': 1})
        quiz_pid = p.get('paper_id') or p.get('id') or ''
    except Exception:
        quiz_pid = ''

    course = {
        'day': day, 'title': d.get('title', ''), 'subject': subject,
        'kp_ids': kp_ids, 'kp_names': kp_names,
        'lesson': lesson, 'quiz_pid': quiz_pid,
        'created': time.time(),
    }
    dset.setdefault('courses', {})[str(day)] = course
    if len(dset['courses']) > MAX_DAYS:
        for k in sorted(dset['courses'], key=lambda x: dset['courses'][x].get('created', 0))[:-MAX_DAYS]:
            dset['courses'].pop(k)
    _save(sid, dset)
    store.log_event(sid, 'daily', {'day': day, 'kps': kp_ids, 'quiz': quiz_pid})
    return course


def memory_weak_top(sid):
    """薄弱考点名（供 prompt），失败返回空。"""
    try:
        m = store.mastery_levels(sid) or {}
        from . import knowledge as _kg
        low = sorted(m.items(), key=lambda kv: kv[1].get('score', 50) if isinstance(kv[1], dict) else 50)[:3]
        return [{'name': (_kg.get_kp(v.get('subject', ''), k) or {}).get('name', k)}
                for k, v in low if isinstance(v, dict)]
    except Exception:
        return []


def summary(sid, day=None):
    """计划页课程区：今天/指定天的课程状态。"""
    plan = store._read_json(store._path(sid, 'plan.json'), None)
    if not plan:
        return None
    today = next((d['day'] for d in plan['days'] if not d.get('status')), None)
    target = int(day) if day else today
    if target is None:
        return {'today': None, 'course': None, 'generated': list_days(sid)}
    d = next((x for x in plan['days'] if x['day'] == target), {})
    course = get(sid, target)
    return {'today': today, 'day': target, 'title': d.get('title', ''),
            'kp_names': [k for k in d.get('kp_ids', [])],
            'has_course': bool(course), 'quiz_pid': (course or {}).get('quiz_pid', ''),
            'generated': list_days(sid)}
