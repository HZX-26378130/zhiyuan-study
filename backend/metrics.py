# -*- coding: utf-8 -*-
"""调用量与运行指标：轻量埋点 + 按天聚合。

为什么单独一个模块：管理端要回答「今天有多少次 AI 调用、失败几次、
哪条通道在扛、谁用得最多」，而这些信息散在日志里读不出来。

存储（都在 data/db/_metrics/ 下，属于运行时数据，不进仓库）：
    llm_calls.jsonl   每次模型调用的明细：时间/账号/通道/成败/耗时
    feedback.jsonl    每次点赞点踩：时间/账号/评价/来源模块

设计取舍：
- 追加写（append-only）+ 单行 JSON，不需要锁也能被并发写（POSIX/Windows 追加是原子的）
- 只保留最近 N 天明细，超出自动裁剪，避免文件无限增长
- 聚合在读时算，管理端按需查询，不预先物化
"""
import json
import os
import threading
import time

from . import store

METRICS_DIR = os.path.join(store.DATA_DIR, 'db', '_metrics')
LLM_FILE = os.path.join(METRICS_DIR, 'llm_calls.jsonl')
FB_FILE = os.path.join(METRICS_DIR, 'feedback.jsonl')
KEEP_DAYS = int(os.environ.get('ZY_METRICS_KEEP_DAYS', '90') or 90)
MAX_BYTES = 8 * 1024 * 1024

_lock = threading.Lock()


def _ensure():
    try:
        os.makedirs(METRICS_DIR, exist_ok=True)
    except OSError:
        return False
    return True


def _append(path, row):
    if not _ensure():
        return
    line = json.dumps(row, ensure_ascii=False) + '\n'
    with _lock:
        try:
            # 简单轮转：超过上限就把旧文件挪成年月存档，避免无限增长
            if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
                os.replace(path, path + '.' + time.strftime('%Y%m'))
        except OSError:
            pass
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
        except OSError:
            pass


def record_llm(channel, ok, ms, sid='', kind='chat', detail=''):
    """记录一次模型调用。channel 是通道名（如「智谱 GLM」）。"""
    _append(LLM_FILE, {
        't': int(time.time()),
        'sid': sid or '',
        'ch': channel or '',
        'ok': 1 if ok else 0,
        'ms': int(ms),
        'k': kind,
        'd': (detail or '')[:200],
    })


def record_feedback(sid, rating, source='', comment=''):
    """记录一次 👍/👎（rating: 1 / -1）。"""
    _append(FB_FILE, {
        't': int(time.time()),
        'sid': sid or '',
        'r': 1 if rating > 0 else -1,
        'src': (source or '')[:40],
        'c': (comment or '')[:200],
    })


def _iter(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _day(ts):
    return time.strftime('%Y-%m-%d', time.localtime(ts))


def llm_series(days=30):
    """按天汇总模型调用：[{day, calls, ok, fail, ms_avg}]"""
    since = time.time() - days * 86400
    buckets = {}
    for row in _iter(LLM_FILE):
        t = row.get('t') or 0
        if t < since:
            continue
        d = _day(t)
        b = buckets.setdefault(d, {'day': d, 'calls': 0, 'ok': 0, 'fail': 0, 'ms': 0})
        b['calls'] += 1
        if row.get('ok'):
            b['ok'] += 1
        else:
            b['fail'] += 1
        b['ms'] += row.get('ms') or 0
    out = []
    for d in sorted(buckets):
        b = buckets[d]
        b['ms_avg'] = int(b['ms'] / b['calls']) if b['calls'] else 0
        b.pop('ms', None)
        out.append(b)
    return out


def llm_by_channel(days=30):
    """各通道调用量与失败率。"""
    since = time.time() - days * 86400
    agg = {}
    for row in _iter(LLM_FILE):
        t = row.get('t') or 0
        if t < since:
            continue
        ch = row.get('ch') or '未知'
        a = agg.setdefault(ch, {'channel': ch, 'calls': 0, 'fail': 0, 'ms_sum': 0})
        a['calls'] += 1
        if not row.get('ok'):
            a['fail'] += 1
        a['ms_sum'] += row.get('ms') or 0
    out = []
    for a in agg.values():
        a['ms_avg'] = int(a['ms_sum'] / a['calls']) if a['calls'] else 0
        a['fail_rate'] = round(a['fail'] * 100.0 / a['calls'], 1) if a['calls'] else 0
        a.pop('ms_sum', None)
        out.append(a)
    out.sort(key=lambda x: -x['calls'])
    return out


def llm_by_user(days=30, limit=50):
    """按账号汇总（谁用得最多 + 谁总失败）。"""
    since = time.time() - days * 86400
    agg = {}
    for row in _iter(LLM_FILE):
        t = row.get('t') or 0
        if t < since:
            continue
        sid = row.get('sid') or '?'
        a = agg.setdefault(sid, {'sid': sid, 'calls': 0, 'fail': 0})
        a['calls'] += 1
        if not row.get('ok'):
            a['fail'] += 1
    out = sorted(agg.values(), key=lambda x: -x['calls'])[:limit]
    return out


def llm_totals(days=30):
    s = llm_series(days)
    calls = sum(x['calls'] for x in s)
    fail = sum(x['fail'] for x in s)
    return {
        'calls': calls,
        'fail': fail,
        'ok_rate': round((calls - fail) * 100.0 / calls, 1) if calls else 100.0,
        'today': next((x['calls'] for x in s if x['day'] == _day(time.time())), 0),
        'ms_avg': (sum(x['ms_avg'] * x['calls'] for x in s) // calls) if calls else 0,
    }


def feedback_series(days=30):
    since = time.time() - days * 86400
    buckets = {}
    for row in _iter(FB_FILE):
        t = row.get('t') or 0
        if t < since:
            continue
        d = _day(t)
        b = buckets.setdefault(d, {'day': d, 'up': 0, 'down': 0})
        if (row.get('r') or 0) > 0:
            b['up'] += 1
        else:
            b['down'] += 1
    return [buckets[d] for d in sorted(buckets)]


def feedback_totals(days=30):
    s = feedback_series(days)
    up = sum(x['up'] for x in s)
    down = sum(x['down'] for x in s)
    total = up + down
    return {'up': up, 'down': down, 'total': total,
            'positive_rate': round(up * 100.0 / total, 1) if total else None,
            'today': next((x['up'] + x['down'] for x in s if x['day'] == _day(time.time())), 0)}


def prune(days=None):
    """裁掉超过保留期的明细（管理端可手动调用）。"""
    days = days or KEEP_DAYS
    cutoff = time.time() - days * 86400
    removed = 0
    for path in (LLM_FILE, FB_FILE):
        if not os.path.exists(path):
            continue
        kept = []
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if (row.get('t') or 0) >= cutoff:
                        kept.append(line)
                    else:
                        removed += 1
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write('\n'.join(kept) + ('\n' if kept else ''))
            os.replace(tmp, path)
        except OSError:
            continue
    return removed
