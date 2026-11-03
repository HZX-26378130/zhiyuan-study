# -*- coding: utf-8 -*-
"""任务积分引擎（融合自 task-points 项目）。
核心原则：
1. 积分账本 earn 只增不删（防篡改）——取消勾选/撤销兑换不再回收积分；
2. 系统任务（source 非空）只能由知源学伴的真实学习行为自动完成；
3. 每次真实学习行为自动发分（RULES），任务完成另有任务分。
"""
import datetime
import json
import threading
import time
import uuid

from . import store

_lock = threading.Lock()

RULES = {'qa': 2, 'english': 5, 'notes': 8, 'paper': 10}  # quiz: 答对题数×2
DEF_CATS = ['学习', '工作', '生活', '运动']
_AUTO_TITLE = {'qa': '完成一次 AI 问答', 'english': '完成一次英语批改',
               'notes': '生成一份薄弱点讲义', 'paper': '完成一份知识诊断卷'}


def _path(sid):
    return store._path(sid, 'points.json')


def _default():
    return {'tasks': [], 'rewards': [], 'earn': [], 'spent': [], 'cats': DEF_CATS[:],
            'goal': 30, 'weekGoal': 150}


def load(sid):
    with _lock:
        try:
            with open(_path(sid), encoding='utf-8') as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
    s = _default()
    for k in s:
        if k in state and state[k] is not None:
            s[k] = state[k]
    if not isinstance(s['cats'], list) or not s['cats']:
        s['cats'] = DEF_CATS[:]
    roll_repeat(s)
    return s


def save(sid, s):
    with _lock:
        store._write_json(_path(sid), s)


# ---------- 时间工具 ----------

def day_key(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def week_start(ts=None):
    d = datetime.datetime.fromtimestamp(ts or time.time())
    monday = d - datetime.timedelta(days=d.weekday())
    return datetime.datetime(monday.year, monday.month, monday.day).timestamp()


# ---------- 账本 ----------

def award(s, pts, title, cat, src):
    """入账：同 src 只入一次（防重复/防刷）。返回实际入账分数。"""
    pts = int(pts or 0)
    if pts <= 0:
        return 0
    if src:
        for e in s['earn']:
            if e.get('src') == src:
                return 0
    s['earn'].append({'id': uuid.uuid4().hex[:12], 'pts': pts, 't': time.time(),
                      'title': title[:80], 'cat': (cat or '学习')[:20], 'src': src})
    return pts


def day_map(s, max_days=120):
    m, cutoff = {}, time.time() - max_days * 86400
    for e in s['earn']:
        if e['t'] >= cutoff:
            k = day_key(e['t'])
            m[k] = m.get(k, 0) + e['pts']
    return m


def balance(s):
    return sum(e['pts'] for e in s['earn']) - sum(x['cost'] for x in s['spent'])


# ---------- 重复任务重置 ----------

def roll_repeat(s):
    kd, kw = day_key(time.time()), day_key(week_start())
    for t in s['tasks']:
        if t.get('repeat') in ('day', 'week'):
            k = kd if t['repeat'] == 'day' else kw
            if t.get('pk') != k:
                if t.get('done'):
                    t['done'] = False
                    t['doneAt'] = None
                t['pk'] = k


# ---------- 学习行为 → 积分（模块钩子） ----------

def notify(sid, etype, payload=None):
    """学习行为发分 + 自动完成关联任务。在 qa/vocab/english/paper/notes 各模块调用。"""
    payload = payload or {}
    s = load(sid)
    total = 0
    if etype == 'quiz':
        pts = int(payload.get('right', 0)) * 2
        title = '词汇测验答对 %s 题' % payload.get('right', 0)
    else:
        pts = RULES.get(etype, 0)
        title = _AUTO_TITLE.get(etype, etype)
    total += award(s, pts, title, '学习', 'auto:%s:%s' % (etype, time.time_ns()))
    # 自动完成 source 匹配的系统任务
    for t in s['tasks']:
        if not t.get('done') and t.get('source') == 'zy:' + etype:
            total += _complete(s, t)
    save(sid, s)
    return total


def notify_kp(sid, subject, kp_id):
    """知识点正向事件（如诊断卷答对）→ 完成对应薄弱点任务。"""
    s = load(sid)
    total = 0
    target = 'zy:kp:%s:%s' % (subject, kp_id)
    for t in s['tasks']:
        if not t.get('done') and t.get('source') == target:
            total += _complete(s, t)
    if total:
        save(sid, s)
    return total


def _complete(s, t):
    t['done'] = True
    t['doneAt'] = time.time()
    return award(s, t.get('pts', 0), '完成任务「%s」' % t['title'], t.get('cat', '学习'),
                 'taskdone:%s:%s' % (t['id'], t.get('pk') or 'once'))


# ---------- 任务 ----------

def add_task(sid, f):
    s = load(sid)
    title = (f.get('title') or '').strip()
    if not title:
        return None
    repeat = f.get('repeat') if f.get('repeat') in ('none', 'day', 'week') else 'none'
    t = {'id': uuid.uuid4().hex[:12], 'title': title[:120],
         'cat': (f.get('cat') or s['cats'][0] if s['cats'] else '学习')[:20],
         'pri': int(f.get('pri', 2)) if int(f.get('pri', 2)) in (1, 2, 3) else 2,
         'pts': max(0, int(f.get('pts', 5))),
         'done': False, 'doneAt': None,
         'repeat': repeat, 'dueT': f.get('dueT') or None, 'dueW': f.get('dueW'),
         'due': f.get('due'), 'source': (f.get('source') or '').strip()[:60]}
    if repeat != 'none':
        t['pk'] = day_key(time.time()) if repeat == 'day' else day_key(week_start())
    s['tasks'].append(t)
    save(sid, s)
    return t


def toggle_task(sid, tid):
    s = load(sid)
    t = next((x for x in s['tasks'] if x['id'] == tid), None)
    if not t:
        return None, '任务不存在'
    if t.get('source'):
        return None, '系统任务由学习行为自动完成，不能手动勾选'
    if not t['done']:
        t['done'] = True
        t['doneAt'] = time.time()
        pk = t.get('pk') or 'once'
        award(s, t['pts'], '完成任务「%s」' % t['title'], t.get('cat', '学习'),
              'task:%s:%s' % (tid, pk))  # 同周期重复勾选不重复计分；取消勾选不退分
    else:
        t['done'] = False
        t['doneAt'] = None
    save(sid, s)
    return t, None


def delete_task(sid, tid):
    s = load(sid)
    before = len(s['tasks'])
    s['tasks'] = [x for x in s['tasks'] if x['id'] != tid]
    changed = len(s['tasks']) < before
    if changed:
        save(sid, s)
    return changed


# ---------- 奖励 ----------

def _used_of(s, r):
    if r.get('period', 'none') == 'day':
        today = day_key(time.time())
        return len([x for x in s['spent'] if x['rid'] == r['id'] and day_key(x['t']) == today])
    if r.get('period') == 'week':
        ws = week_start()
        return len([x for x in s['spent'] if x['rid'] == r['id'] and x['t'] >= ws])
    return len([x for x in s['spent'] if x['rid'] == r['id']])


def add_reward(sid, f):
    s = load(sid)
    name = (f.get('name') or '').strip()
    if not name:
        return None
    r = {'id': uuid.uuid4().hex[:12], 'name': name[:60],
         'cost': max(1, int(f.get('cost', 20))),
         'period': f.get('period') if f.get('period') in ('none', 'day', 'week', 'total') else 'none',
         'limit': max(1, int(f.get('limit', 1)))}
    s['rewards'].append(r)
    save(sid, s)
    return r


def update_reward(sid, rid, k, v):
    s = load(sid)
    r = next((x for x in s['rewards'] if x['id'] == rid), None)
    if not r:
        return None
    if k == 'period':
        r['period'] = v if v in ('none', 'day', 'week', 'total') else 'none'
    elif k == 'limit':
        r['limit'] = max(1, int(v or 1))
    save(sid, s)
    return r


def redeem(sid, rid):
    s = load(sid)
    r = next((x for x in s['rewards'] if x['id'] == rid), None)
    if not r:
        return None, '奖励不存在'
    b = balance(s)
    if b < r['cost']:
        return None, '积分不足：需要 %d，当前 %d' % (r['cost'], b)
    if r['period'] != 'none' and _used_of(s, r) >= r['limit']:
        return None, '已达限购上限'
    s['spent'].append({'id': uuid.uuid4().hex[:12], 'rid': r['id'], 'name': r['name'],
                       'cost': r['cost'], 't': time.time()})
    save(sid, s)
    return r, None


def delete_reward(sid, rid):
    s = load(sid)
    s['rewards'] = [x for x in s['rewards'] if x['id'] != rid]
    save(sid, s)


def undo_spent(sid, spid):
    s = load(sid)
    s['spent'] = [x for x in s['spent'] if x['id'] != spid]
    save(sid, s)


# ---------- 分类 / 设置 ----------

def cats_op(sid, op, name):
    s = load(sid)
    name = (name or '').strip()[:20]
    if not name:
        return '名称不能为空'
    if op == 'add':
        if name not in s['cats']:
            s['cats'].append(name)
    elif op == 'del':
        if len(s['cats']) <= 1:
            return '至少保留一个分类'
        to = next(c for c in s['cats'] if c != name)
        for t in s['tasks']:
            if t.get('cat') == name:
                t['cat'] = to
        s['cats'] = [c for c in s['cats'] if c != name]
    save(sid, s)
    return None


def settings(sid, goal=None, week_goal=None):
    s = load(sid)
    if goal is not None:
        s['goal'] = max(0, int(goal))
    if week_goal is not None:
        s['weekGoal'] = max(0, int(week_goal))
    save(sid, s)


# ---------- 补签 / 模拟跨天 ----------

def makeup(sid):
    """为昨天补一次达标（每周限 2 次）：昨日积分补到 goal。"""
    s = load(sid)
    if s['goal'] <= 0:
        return None, '请先设置每日积分要求'
    y = time.time() - 86400
    yk = day_key(y)
    if day_key(time.time()) == yk:
        return None, '不存在可补的昨天'
    m = day_map(s, max_days=400)
    if m.get(yk, 0) >= s['goal']:
        return None, '昨天已达标，无需补签'
    wk = day_key(week_start())
    used = len([e for e in s['earn'] if (e.get('src') or '').startswith('makeup:' + wk)])
    if used >= 2:
        return None, '本周补签次数已用完（每周 2 次）'
    award(s, s['goal'], '补签 %s' % yk, '学习', 'makeup:%s:%d' % (wk, used + 1))
    s['earn'][-1]['t'] = datetime.datetime.fromtimestamp(y).replace(hour=12).timestamp()
    save(sid, s)
    return True, None


def simulate_day(sid):
    s = load(sid)
    for t in s['tasks']:
        if t.get('repeat') == 'day':
            t['pk'] = '2000-01-01'
        elif t.get('repeat') == 'week':
            t['pk'] = '2000-01-03'
    roll_repeat(s)
    save(sid, s)


# ---------- 统计 ----------

def runs_of(s):
    """所有达标日按连续天数分组。"""
    g = s['goal']
    if g <= 0:
        return []
    m = day_map(s, max_days=400)
    if not m:
        return []
    ks = sorted(m.keys())
    d0 = datetime.datetime.strptime(ks[0], '%Y-%m-%d').date()
    d1 = datetime.datetime.strptime(day_key(time.time()), '%Y-%m-%d').date()
    out, cur = [], None
    d = d0
    while d <= d1:
        k = d.strftime('%Y-%m-%d')
        if m.get(k, 0) >= g:
            ts = datetime.datetime(d.year, d.month, d.day).timestamp()
            if cur and cur['end'] == ts - 86400:
                cur['end'] = ts
                cur['n'] += 1
            else:
                cur = {'start': ts, 'end': ts, 'n': 1}
                out.append(cur)
        d += datetime.timedelta(days=1)
    return out


def stats(s):
    now = time.time()
    m = day_map(s)
    today = m.get(day_key(now), 0)
    ws = week_start()
    week = sum(e['pts'] for e in s['earn'] if e['t'] >= ws)
    # streak：今天未达标则从昨天起算
    streak, d = 0, datetime.datetime.fromtimestamp(now).date()
    if s['goal'] > 0 and today < s['goal']:
        d -= datetime.timedelta(days=1)
    while s['goal'] > 0 and m.get(d.strftime('%Y-%m-%d'), 0) >= s['goal']:
        streak += 1
        d -= datetime.timedelta(days=1)
        if streak > 3650:
            break
    return {'balance': balance(s), 'today': today, 'week': week, 'streak': streak,
            'goal': s['goal'], 'weekGoal': s['weekGoal'], 'runs': runs_of(s)[-3:],
            'dayMap': m, 'earnCount': len(s['earn']), 'spentCount': len(s['spent'])}


def full_state(sid):
    s = load(sid)
    return {'tasks': s['tasks'], 'rewards': s['rewards'], 'cats': s['cats'],
            'earn': s['earn'][-80:], 'spent': s['spent'][-80:], 'stats': stats(s)}


# ---------- 导入 task-points 备份 ----------

def import_backup(sid, data):
    if not isinstance(data, dict) or not isinstance(data.get('tasks'), list):
        return None, '备份格式不对：缺少 tasks 数组'
    s = _default()
    s['tasks'] = data.get('tasks', [])
    s['rewards'] = data.get('rewards', [])
    s['cats'] = data.get('cats') or DEF_CATS[:]
    s['goal'] = int(data.get('goal', 30) or 30)
    s['weekGoal'] = int(data.get('weekGoal', 150) or 150)
    for e in data.get('earn', []):
        s['earn'].append({'id': uuid.uuid4().hex[:12], 'pts': int(e.get('pts', 0)),
                          't': float(e.get('t', time.time())), 'title': str(e.get('title', ''))[:80],
                          'cat': str(e.get('cat', '学习'))[:20], 'src': 'import:' + str(e.get('id', ''))})
    for x in data.get('spent', []):
        s['spent'].append({'id': uuid.uuid4().hex[:12], 'rid': str(x.get('rid', '')),
                           'name': str(x.get('name', ''))[:60], 'cost': int(x.get('cost', 0)),
                           't': float(x.get('t', time.time()))})
    for t in s['tasks']:
        t['source'] = t.get('source', '')
        t.setdefault('done', False)
        t.setdefault('doneAt', None)
        if t.get('repeat') in ('day', 'week'):
            t['pk'] = day_key(time.time()) if t['repeat'] == 'day' else day_key(week_start())
    save(sid, s)
    return {'tasks': len(s['tasks']), 'earn': len(s['earn'])}, None
