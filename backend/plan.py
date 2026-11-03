# -*- coding: utf-8 -*-
"""学习计划（定路线）：吸收 good-learning「知识清单 + 备考计划分离」与 Study-Mate「定路线」理念。
确定性排课为骨架（考点拓扑序 + 薄弱优先 + 掌握度筛选），LLM 只润色每日主题与目标——
离线也能生成可用计划；按实际完成发分（复用积分防刷账本）并给出节奏预警。"""
import datetime
import json
import time

from . import knowledge, llm, points, store

PER_DAY_MINUTES = 35          # 每个考点约 35 分钟
MAX_DAYS = 45
DONE_PTS = 8


def _path(sid):
    return store._path(sid, 'plan.json')


def _load(sid):
    return store._read_json(_path(sid), None)


def _save(sid, plan):
    store._write_json(_path(sid), plan)


def get(sid):
    plan = _load(sid)
    if not plan:
        return None
    return _decorate(sid, plan)


def delete(sid):
    if _load(sid):
        store._write_json(_path(sid), None)
        return True
    return False


def _topo_kps(subject):
    """考点按前置依赖拓扑排序（Kahn），同层按名称稳定排序。"""
    kps = (knowledge.get_subject(subject) or {}).get('kps') or {}
    indeg = {k: len(set(kp.get('prereqs') or []) & set(kps)) for k, kp in kps.items()}
    dependents = {k: [] for k in kps}
    for k, kp in kps.items():
        for p in set(kp.get('prereqs') or []) & set(kps):
            dependents[p].append(k)
    queue = sorted([k for k, d in indeg.items() if d == 0], key=lambda k: kps[k]['name'])
    out = []
    while queue:
        k = queue.pop(0)
        out.append(k)
        for nxt in dependents[k]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
                queue.sort(key=lambda x: kps[x]['name'])
    for k in kps:  # 防御：循环依赖兜底
        if k not in out:
            out.append(k)
    return out, kps


def _pick_kps(sid, subject, level):
    """按起点筛选考点：零基础全学；复习模式跳过已掌握(≥85)。薄弱考点集中在前半段攻克。"""
    order, kps = _topo_kps(subject)
    mastery = store.mastery_levels(sid) or {}
    weak = set()
    for k in order:
        rec = mastery.get(k) or {}
        score = rec.get('score', 50) if isinstance(rec, dict) else 50
        if level == 'review' and score >= 85:
            continue
        if score < 50:
            weak.add(k)
    ordered = [k for k in order if k in weak] + [k for k in order if k not in weak
                                                 and not (level == 'review' and (mastery.get(k) or {}).get('score', 50) >= 85)]
    return ordered, kps


def _fallback_plan(sid, subject, level, daily_minutes):
    """离线/兜底：确定性排课。"""
    per_day = max(1, round(daily_minutes / PER_DAY_MINUTES))
    kps_ordered, kps = _pick_kps(sid, subject, level)
    days = []
    for i in range(0, len(kps_ordered), per_day):
        chunk = kps_ordered[i:i + per_day]
        days.append({
            'kp_ids': chunk,
            'title': '、'.join(kps[k]['name'] for k in chunk),
            'objectives': [o for k in chunk for o in kps[k].get('key_points', [])[:1]],
            'minutes': min(daily_minutes, PER_DAY_MINUTES * len(chunk)),
        })
    return days


def _llm_polish(sid, subject, draft, goal, exam_date, level):
    """LLM 润色每日主题与目标（结构不变、考点不变；失败回退草稿）。"""
    if not llm.available() or not draft:
        return draft
    kps = (knowledge.get_subject(subject) or {}).get('kps') or {}
    try:
        res = llm.chat_json([
            {'role': 'user', 'content':
                '你是学习规划师。科目：%s；学生目标：%s；考试日期：%s；起点：%s。\n'
                '下面是一份逐日计划的考点骨架（每天 kp_ids 固定，不可增删）。'
                '请为每天润色：title（当天主题，一句话有吸引力）、'
                'objectives（2-3条可验收的学习目标，具体到"会做什么"）。'
                '只允许改 title/objectives/minutes，不得增删 kp_ids 或天数。'
                '输出 JSON：{"days":[{"day":n,"title":"...","objectives":["..."],"minutes":n}]}\n\n'
                '计划骨架：%s'
                % (knowledge.subjects().get(subject, subject), goal or '掌握核心考点',
                   exam_date or '未定', '零基础' if level == 'zero' else '复习',
                   json.dumps([{'day': i + 1, 'kp_ids': d['kp_ids'], 'title': d['title']}
                               for i, d in enumerate(draft)], ensure_ascii=False))
            }], temperature=0.4, max_tokens=3000)
        days_out = (res or {}).get('days') or []
        if len(days_out) != len(draft):
            return draft
        polished = []
        for i, d in enumerate(days_out):
            base = draft[i]
            polished.append({
                'kp_ids': base['kp_ids'],  # 锁死
                'title': str(d.get('title') or base['title'])[:80],
                'objectives': [str(o)[:80] for o in (d.get('objectives') or base['objectives'])][:3],
                'minutes': int(d.get('minutes') or base['minutes']),
            })
        return polished
    except llm.LLMError:
        return draft


def create(sid, subject, goal, exam_date, daily_minutes, level):
    if not knowledge.get_subject(subject):
        raise ValueError('暂不支持该科目：' + str(subject))
    if _load(sid):
        raise ValueError('已有学习计划，请先删除再创建')
    daily_minutes = max(15, min(int(daily_minutes or 40), 180))
    level = 'zero' if level == 'zero' else 'review'
    draft = _fallback_plan(sid, subject, level, daily_minutes)
    if not draft:
        raise ValueError('没有可规划的考点（可能已全部掌握）')
    days = _llm_polish(sid, subject, draft, goal, exam_date, level)[:MAX_DAYS]
    days = [dict(d, day=i + 1) for i, d in enumerate(days)]
    plan = {
        'subject': subject, 'goal': str(goal or '')[:60],
        'exam_date': str(exam_date or '')[:10], 'daily_minutes': daily_minutes,
        'level': level, 'created': time.time(), 'days': days,
    }
    _save(sid, plan)
    store.log_event(sid, 'plan', {'action': 'create', 'subject': subject, 'days': len(days)})
    return _decorate(sid, plan)


def mark_done(sid, day, score=None):
    """完成一天的学习：发分（同一天只发一次）+ 记录。"""
    plan = _load(sid)
    if not plan:
        raise ValueError('还没有学习计划')
    d = next((x for x in plan['days'] if x['day'] == int(day)), None)
    if not d:
        raise ValueError('计划里没有这一天')
    awarded = 0
    if not d.get('status'):
        d['status'] = 'done'
        d['done_ts'] = time.time()
        try:
            p = points.load(sid)
            awarded = points.award(p, DONE_PTS, '完成学习计划 D%d：%s' % (day, d['title'][:20]),
                                   '学习', 'zy:plan:%s:%d' % (plan['subject'], day))
            points.save(sid, p)
        except Exception:
            awarded = 0
    if score is not None:
        d['score'] = max(0, min(100, int(score)))
    _save(sid, plan)
    store.log_event(sid, 'plan', {'action': 'done', 'day': day, 'awarded': awarded})
    return _decorate(sid, plan), awarded


def _decorate(sid, plan):
    """补充今天位置、进度、节奏预警。"""
    done = sum(1 for d in plan['days'] if d.get('status') == 'done')
    today = next((d['day'] for d in plan['days'] if not d.get('status')), None)
    out = dict(plan)
    out['done_n'] = done
    out['total_n'] = len(plan['days'])
    out['today'] = today
    out['subject_name'] = knowledge.subjects().get(plan['subject'], plan['subject'])
    out['pace_warning'] = ''
    if plan.get('exam_date'):
        try:
            left = (datetime.date.fromisoformat(plan['exam_date']) - datetime.date.today()).days
            out['days_to_exam'] = max(left, 0)
            remain = len(plan['days']) - done
            if left >= 0 and remain > left:
                out['pace_warning'] = '按当前节奏还需 %d 天，距考试只有 %d 天——考虑增加每日时长或精简考点' % (remain, left)
            elif left >= 0:
                out['pace_warning'] = '距考试 %d 天，剩余 %d 天课程，节奏正常' % (left, remain)
        except ValueError:
            pass
    return out


def summary_for_dashboard(sid):
    """仪表盘卡片：今天的任务。"""
    plan = _load(sid)
    if not plan:
        return None
    today = next((d for d in plan['days'] if not d.get('status')), None)
    done = sum(1 for d in plan['days'] if d.get('status') == 'done')
    return {'subject': plan['subject'], 'subject_name': knowledge.subjects().get(plan['subject'], ''),
            'goal': plan.get('goal', ''), 'done_n': done, 'total_n': len(plan['days']),
            'today_day': today['day'] if today else None,
            'today_title': today['title'] if today else '（已全部完成 🎉）',
            'pace_warning': _decorate(sid, plan).get('pace_warning', '')}
