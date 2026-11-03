# -*- coding: utf-8 -*-
"""存储层：学生档案、掌握度、历史记录、试卷、资料、生词本。
本地模式 = JSON 文件（data/db/）；云端模式（设置 ZY_DB_URL 环境变量）= db-proxy 云函数 → CloudBase 数据库，
带进程内写穿缓存。图片附件两种模式都存本地磁盘（云端为实例临时盘，可重新上传）。"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 数据目录：默认项目内 data/，可用 ZY_DATA_DIR 覆盖。
# exe 打包后程序目录可能是只读/临时的（PyInstaller 会解压到临时目录），
# 因此必须允许把数据落到用户可写目录（如 %APPDATA%\知源学伴）。
DATA_DIR = os.path.abspath(os.environ.get('ZY_DATA_DIR') or os.path.join(BASE, 'data'))
DB_DIR = os.path.join(DATA_DIR, 'db')

_lock = threading.RLock()  # 可重入：云端分支在持锁写文件时会再次获取（save_profile → _write_json）

# ---------- 云端适配（PostgreSQL 环境 RDB REST，PostgREST 风格） ----------

ZY_DB_URL = os.environ.get('ZY_DB_URL', '').rstrip('/')
ZY_DB_KEY = os.environ.get('ZY_DB_KEY', '')
_cache = {}


def cloud_enabled():
    return bool(ZY_DB_URL)


def _rdb(method, path, payload=None, prefer=None, tries=2, timeout=12):
    """RDB REST 调用，带瞬时失败重试。绕过系统代理直连（国内网关 + 本地 Clash 代理会丢包/挂起）。
    timeout 收紧到 12s：仪表盘等非关键聚合失败时快速兜底，不拖住整页。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(ZY_DB_URL + path, method=method)
            req.add_header('Authorization', 'Bearer ' + ZY_DB_KEY)
            req.add_header('Accept', 'application/json')
            if payload is not None:
                req.add_header('Content-Type', 'application/json')
                if prefer:
                    req.add_header('Prefer', prefer)
                req.data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            with _DIRECT.open(req, timeout=timeout) as r:
                return r.status, (r.read().decode('utf-8', 'replace') if r.status != 204 else '')
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code < 500 and e.code != 429:
                return e.code, body
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(0.4 * (i + 1))
    raise OSError('rdb %s %s: %r' % (method, path, last))


# 不走系统代理的直连 opener（CloudBase 国内网关直连稳定；本地代理会间歇性丢包）
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _rows(body):
    try:
        return json.loads(body) if body else []
    except ValueError:
        return []


def db_get_json(key):
    from urllib.parse import quote
    s, body = _rdb('GET', '/zy_store?select=val&key=eq.' + quote(key, safe=''))
    rows = _rows(body)
    return rows[0].get('val') if rows and isinstance(rows[0], dict) else None


def db_put_json(key, obj):
    from urllib.parse import quote
    _rdb('POST', '/zy_store', {'key': key, 'val': obj, 'up': int(time.time())},
         prefer='resolution=merge-duplicates')


def db_del(key):
    from urllib.parse import quote
    _rdb('DELETE', '/zy_store?key=eq.' + quote(key, safe=''))


def db_list_keys(prefix):
    """列出前缀下的 key（降序，与本地 listdir 的 reverse 一致）。"""
    from urllib.parse import quote
    pat = quote(prefix + '*', safe='')
    s, body = _rdb('GET', '/zy_store?select=key&key=like.' + pat)
    return [r['key'].rsplit('/', 1)[-1] for r in _rows(body) if isinstance(r, dict) and r.get('key')]


def db_user_get(name):
    from urllib.parse import quote
    s, body = _rdb('GET', '/zy_users?select=*&name=eq.' + quote(name, safe=''))
    rows = _rows(body)
    return rows[0] if rows else None


def db_user_add(uid, name, salt, phash):
    _rdb('POST', '/zy_users', {'uid': uid, 'name': name, 'salt': salt, 'hash': phash, 'created': int(time.time())})


def db_users_all():
    """云端：全部注册用户（uid+name，用于全员聚合学习）。"""
    s, body = _rdb('GET', '/zy_users?select=uid,name&order=created.asc&limit=200')
    return [r for r in _rows(body) if isinstance(r, dict) and r.get('uid')]


# ---------- 账号存储：云端走 RDB，本地/自托管走 users.json ----------
# 这样 ZY_AUTH=1 在「没有 PostgreSQL」的自托管场景下也能注册登录，
# 否则只能用裸奔模式（无鉴权）暴露到公网。

USERS_FILE = 'users.json'


def user_get(name):
    """按用户名取账号记录 {uid,name,salt,hash,created}。"""
    if cloud_enabled():
        return db_user_get(name)
    idx = _read_json(_path(USERS_FILE), {}) or {}
    return idx.get(name)


def user_add(uid, name, salt, phash):
    if cloud_enabled():
        return db_user_add(uid, name, salt, phash)
    with _lock:
        idx = _read_json(_path(USERS_FILE), {}) or {}
        idx[name] = {'uid': uid, 'name': name, 'salt': salt, 'hash': phash,
                     'created': int(time.time())}
        _write_json(_path(USERS_FILE), idx)


def users_all():
    """全部账号（uid+name）。"""
    if cloud_enabled():
        return db_users_all()
    idx = _read_json(_path(USERS_FILE), {}) or {}
    return [{'uid': v.get('uid'), 'name': k} for k, v in idx.items() if v.get('uid')]


def all_sids():
    """所有学生档案 id：云端 = 全部注册用户；本地 = students.json 全部档案 + 本地注册账号。"""
    if cloud_enabled():
        try:
            return [u['uid'] for u in db_users_all()]
        except OSError:
            return []
    sids = list(list_students().keys())
    for u in users_all():          # 自托管账号模式下注册的用户
        if u['uid'] not in sids:
            sids.append(u['uid'])
    return sids


def _key_of(path):
    return os.path.relpath(path, DB_DIR).replace('\\', '/')


def _path(*parts):
    return os.path.join(DB_DIR, *parts)


def _read_json(path, default):
    if cloud_enabled():
        key = _key_of(path)
        with _lock:
            if key in _cache:
                return _cache[key]
        try:
            val = db_get_json(key)
        except OSError:
            return default
        if val is None or not isinstance(val, (dict, list)):
            val = default
        with _lock:
            _cache[key] = val
        return val
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    if cloud_enabled():
        key = _key_of(path)
        db_put_json(key, obj)
        with _lock:
            _cache[key] = obj
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


_HISTORY_CAP = 2000


def _append_jsonl(path, obj):
    if cloud_enabled():
        key = _key_of(path)
        with _lock:
            rows = _cache.get(key)
            if rows is None:
                try:
                    rows = db_get_json(key)
                except OSError:
                    rows = None
                if not isinstance(rows, list):
                    rows = []
            rows = (rows + [obj])[-_HISTORY_CAP:]
            _cache[key] = rows
        db_put_json(key, rows)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def _read_jsonl(path):
    """get_history 专用：云端读 DB 列表，本地读文件行。"""
    if cloud_enabled():
        return list(_read_json(path, []) or [])
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _list_dir(rel_dir):
    """列目录下的文件名（云端用 like 前缀查询）。"""
    if cloud_enabled():
        try:
            return db_list_keys(rel_dir + '/')
        except OSError:
            return []
    d = _path(rel_dir)
    if not os.path.isdir(d):
        return []
    return sorted(os.listdir(d), reverse=True)


def new_id():
    return uuid.uuid4().hex[:12]


DEFAULT_PROFILE = {
    'name': '',
    'created_at': None,
    'mastery': {},   # kp_id -> {score, hits, wrong, last, subject}
    'wordbook': {},  # word -> {level, right, wrong, meaning, last}
    'memory': {
        'preferences': [],
        'strategy': '',
        'strategy_updated': None,
        'feedback': [],   # {ts, module, target, rating, comment}
    },
    'stats': {'qa': 0, 'graded': 0, 'quiz_done': 0, 'papers_done': 0, 'notes': 0},
}

# ---------- 学生档案 ----------

def list_students():
    idx = _read_json(_path('students.json'), {})
    return idx


def create_student(name):
    with _lock:
        idx = list_students()
        sid = new_id()
        prof = dict(DEFAULT_PROFILE)
        prof = json.loads(json.dumps(DEFAULT_PROFILE))  # deep copy
        prof['name'] = name or ('学生' + sid[:4])
        prof['created_at'] = time.time()
        idx[sid] = {'name': prof['name'], 'created_at': prof['created_at']}
        _write_json(_path('students.json'), idx)
        _write_json(_path(sid, 'profile.json'), prof)
        return sid, prof


def get_profile(sid):
    prof = _read_json(_path(sid, 'profile.json'), None)
    if prof is None:
        # 自动建号，方便本地使用
        idx = list_students()
        if sid in idx:
            prof = json.loads(json.dumps(DEFAULT_PROFILE))
            prof['name'] = idx[sid].get('name', sid)
            prof['created_at'] = idx[sid].get('created_at') or time.time()
            _write_json(_path(sid, 'profile.json'), prof)
    return prof


def save_profile(sid, prof):
    with _lock:
        _write_json(_path(sid, 'profile.json'), prof)


def init_profile(sid, name):
    """云端注册时直接初始化档案（不走 students.json 共享索引）。"""
    prof = json.loads(json.dumps(DEFAULT_PROFILE))
    prof['name'] = name or ('学生' + sid[:4])
    prof['created_at'] = time.time()
    save_profile(sid, prof)
    return prof


def get_student_summary(sid):
    idx = list_students()
    info = idx.get(sid)
    if not info:
        # 自托管账号模式：注册用户不会进 students.json，档案直接按 uid 建
        prof0 = get_profile(sid) or {}
        if prof0:
            info = {'name': prof0.get('name', sid), 'created_at': prof0.get('created_at')}
    if not info:
        return None
    prof = get_profile(sid) or {}
    m = prof.get('mastery', {})
    levels = {}
    for kp, v in m.items():
        levels.setdefault(v.get('subject', ''), []).append(v.get('score', 50))
    avg = {s: round(sum(a) / len(a), 1) for s, a in levels.items()}
    return {'id': sid, 'name': info['name'], 'created_at': info['created_at'],
            'kp_count': len(m), 'avg_by_subject': avg, 'stats': prof.get('stats', {})}


# ---------- 掌握度 / 薄弱点 ----------

def update_mastery(sid, kp_id, subject, delta, wrong=False):
    """旧接口：累加式加减分。仅用于「无对错信号」的弱证据（如问过一次）。

    有对错的地方请用 observe_answer（BKT 概率模型）。
    """
    prof = get_profile(sid)
    if prof is None:
        return
    m = prof.setdefault('mastery', {})
    rec = m.get(kp_id) or {'score': 50, 'hits': 0, 'wrong': 0, 'last': 0, 'subject': subject}
    rec['score'] = max(0, min(100, rec['score'] + delta))
    rec['hits'] += 1
    rec['wrong'] += 1 if wrong else 0
    rec['last'] = time.time()
    rec['subject'] = subject
    m[kp_id] = rec
    save_profile(sid, prof)
    return rec


def observe_answer(sid, kp_id, subject, correct):
    """用一次「答对/答错」更新掌握度（BKT 贝叶斯知识追踪）。

    掌握度不再手工加减分，而是维护一个「已掌握概率」：
      · 答对时上调，但会扣掉"蒙对"的可能（p_guess）
      · 答错时下调，但会扣掉"手滑"的可能（p_slip）
      · 每次作答后叠加学习转移（p_learn）：看了讲解也算学到一点
    profile.mastery[kp] 里保留 score（0-100，供雷达图/薄弱点沿用）与 bkt 状态。
    """
    from . import kt
    prof = get_profile(sid)
    if prof is None:
        return None
    m = prof.setdefault('mastery', {})
    rec = m.get(kp_id) or {'score': kt.score(None), 'hits': 0, 'wrong': 0,
                           'last': 0, 'subject': subject}
    state = rec.get('bkt') or kt.new_state(subject)
    if state.get('p') is None:
        state['p'] = kt.params()['p_init']
    state = kt.observe(state, bool(correct))
    state['subject'] = subject
    rec['bkt'] = state
    rec['score'] = kt.score(state)
    rec['hits'] = int(rec.get('hits', 0)) + 1
    rec['wrong'] = int(rec.get('wrong', 0)) + (0 if correct else 1)
    rec['last'] = time.time()
    rec['subject'] = subject
    m[kp_id] = rec
    save_profile(sid, prof)
    return rec


def mastery_levels(sid):
    prof = get_profile(sid) or {}
    return prof.get('mastery', {})


# ---------- 历史 ----------

def log_event(sid, etype, payload):
    with _lock:
        _append_jsonl(_path(sid, 'history.jsonl'),
                      {'ts': time.time(), 'type': etype, **payload})


def get_history(sid, limit=50, etype=None):
    recs = _read_jsonl(_path(sid, 'history.jsonl'))
    if etype:
        recs = [r for r in recs if r.get('type') == etype]
    return recs[-limit:]


# ---------- 试卷 ----------

def save_paper(sid, paper):
    with _lock:
        _write_json(_path(sid, 'papers', paper['id'] + '.json'), paper)


def get_paper(sid, pid):
    return _read_json(_path(sid, 'papers', pid + '.json'), None)


def list_papers(sid):
    out = []
    for fn in _list_dir(sid + '/papers'):
        p = _read_json(_path(sid, 'papers', fn), None)
        if p:
            out.append({k: p.get(k) for k in ('id', 'created', 'subject', 'status', 'score', 'difficulty')})
    return out


# ---------- 讲义 ----------

def save_note(sid, note_id, doc):
    with _lock:
        _write_json(_path(sid, 'notes', note_id + '.json'), doc)


def get_note(sid, nid):
    return _read_json(_path(sid, 'notes', nid + '.json'), None)


def list_notes(sid):
    out = []
    for fn in _list_dir(sid + '/notes'):
        p = _read_json(_path(sid, 'notes', fn), None)
        if p:
            out.append({k: p.get(k) for k in ('id', 'created', 'title', 'kps')})
    return out


# ---------- 图片附件 ----------

import re as _re

_IMG_RE = _re.compile(r'^[a-f0-9]{16}\.(png|jpg|jpeg|webp|gif)$', _re.I)
_IMG_MIME = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
             'webp': 'image/webp', 'gif': 'image/gif'}


def save_image(sid, data, ext):
    ext = ext.lower().lstrip('.')
    if ext not in _IMG_MIME:
        ext = 'png'
    name = '%s.%s' % (uuid.uuid4().hex[:16], ext)
    p = _path(sid, 'images', name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(data)
    return name


def get_image(sid, name):
    if not _IMG_RE.match(name or ''):
        return None, None
    p = _path(sid, 'images', name)
    if not os.path.isfile(p):
        return None, None
    with open(p, 'rb') as f:
        return f.read(), _IMG_MIME[name.rsplit('.', 1)[1].lower()]


# ---------- 校本资料 ----------

def save_material(sid, mat):
    with _lock:
        _write_json(_path(sid, 'materials', mat['id'] + '.json'), mat)


def list_materials(sid):
    out = []
    for fn in sorted(_list_dir(sid + '/materials')):
        m = _read_json(_path(sid, 'materials', fn), None)
        if m:
            out.append({'id': m['id'], 'name': m['name'], 'size': m.get('size', 0),
                        'chunks': len(m.get('chunks', [])), 'created': m.get('created')})
    return out


def get_materials(sid):
    out = []
    for fn in _list_dir(sid + '/materials'):
        m = _read_json(_path(sid, 'materials', fn), None)
        if m:
            out.append(m)
    return out


def delete_material(sid, mid):
    with _lock:
        try:
            os.remove(_path(sid, 'materials', mid + '.json'))
            return True
        except OSError:
            return False
