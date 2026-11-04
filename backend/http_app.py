# -*- coding: utf-8 -*-
"""HTTP 应用：API 路由 + 静态前端服务 + multipart 上传解析（纯标准库）。"""
import hmac
import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

from . import auth, bank, daily, english, external, knowledge, llm, materials, memory, notes, paper, plan, points, qa, search, store, vocab, weekly, wrongbook
from . import admin, archive, metrics, pdftext

# 静态资源目录：exe 打包后由启动器指向解压出来的资源目录
FRONTEND = os.path.abspath(os.environ.get('ZY_FRONTEND') or os.path.join(store.BASE, 'frontend'))

# 安全加固：请求体上限（防内存型 DoS）与合法学生 ID 格式（防路径穿越）
MAX_BODY = 64 * 1024 * 1024
SID_RE = re.compile(r'^[A-Za-z0-9_-]{4,40}$')


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


# ---------------- 管理端鉴权 ----------------
# 目标：**只有管理员本人**能看到入口、能调接口；普通学生连侧栏「管理端」都不出现。
#
# 三种模式（按优先级）：
#   1) ZY_ADMIN_USER=用户名   → 只有这个账号（正常登录后）是管理员  ← 公网部署推荐
#   2) ZY_ADMIN_TOKEN=口令    → 谁持有口令谁是管理员（不必登录）
#   3) 两者都没配 + 单机模式  → 本机即管理员（桌面版 / 自己电脑用）
#   4) 两者都没配 + 多用户    → 管理端整体关闭（不会误把全班数据暴露给所有学生）

def _admin_token():
    return (os.environ.get('ZY_ADMIN_TOKEN') or '').strip()


def _admin_user():
    return (os.environ.get('ZY_ADMIN_USER') or '').strip()


# 口令错误次数节流，防止被暴力猜（内存级，重启即清）
_admin_fails = {}
_ADMIN_FAIL_LIMIT = 8
_ADMIN_FAIL_WINDOW = 300


def _client_ip(ctx):
    try:
        return (ctx.get('headers') or {}).get('X-Forwarded-For', '').split(',')[0].strip() \
            or ctx.get('client_ip') or '?'
    except Exception:  # noqa: BLE001
        return '?'


def _throttle_check(ctx):
    ip = _client_ip(ctx)
    rec = _admin_fails.get(ip)
    if rec and rec[1] > time.time() and rec[0] >= _ADMIN_FAIL_LIMIT:
        raise ApiError(429, '口令错误次数过多，请 5 分钟后再试')
    return ip


def _throttle_hit(ip):
    now = time.time()
    cnt, until = _admin_fails.get(ip, (0, 0))
    if until < now:
        cnt = 0
    _admin_fails[ip] = (cnt + 1, now + _ADMIN_FAIL_WINDOW)


def _throttle_clear(ip):
    _admin_fails.pop(ip, None)


def _account_name(ctx):
    """当前请求对应账号的显示名（用于 ZY_ADMIN_USER 比对）。

    注意：GET 请求通常没有 sid 参数，真实身份在 Authorization 令牌里，
    所以这里优先用令牌解析出的 uid，其次才退回 ctx['sid']。
    """
    sid = ''
    if auth.enabled():
        tok = ((ctx.get('headers') or {}).get('Authorization') or '')[7:].strip()
        if tok:
            sid = auth.verify_token(tok) or ''
    if not sid:
        sid = ctx.get('sid') or ''
    if not sid:
        return ''
    try:
        prof = store.get_profile(sid) or {}
        return prof.get('name') or ''
    except Exception:  # noqa: BLE001
        return ''


def _is_admin(ctx):
    """判断本次请求是否管理员本人。"""
    user = _admin_user()
    tok = _admin_token()
    if user:
        return bool(_account_name(ctx)) and _account_name(ctx) == user
    if tok:
        given = ((ctx.get('query') or {}).get('token')
                 or (ctx.get('headers') or {}).get('X-Admin-Token') or '').strip()
        return bool(given) and hmac.compare_digest(tok, given)
    return not auth.enabled()


def _admin_meta(ctx=None):
    """给前端的元信息：是否允许管理端、当前请求者是否已是管理员、用哪种方式。"""
    user, tok = _admin_user(), _admin_token()
    mode = 'user' if user else ('token' if tok else ('open' if not auth.enabled() else 'off'))
    is_admin = _is_admin(ctx or {}) if mode != 'off' else False
    return {
        'enabled': mode != 'off',
        'mode': mode,
        'need_token': mode == 'token',
        'need_user': mode == 'user',
        'admin_user': user,
        'is_admin': is_admin,
    }


def _admin_guard(ctx):
    meta = _admin_meta(ctx)
    if not meta['enabled']:
        raise ApiError(403, '管理端未启用：请在后端设置 ZY_ADMIN_USER（推荐）或 ZY_ADMIN_TOKEN')
    if _is_admin(ctx):
        if meta['mode'] == 'token':
            _throttle_clear(_client_ip(ctx))
        return
    if meta['mode'] == 'token':
        ip = _throttle_check(ctx)
        _throttle_hit(ip)
        raise ApiError(401, '管理员口令错误')
    if meta['mode'] == 'user':
        raise ApiError(403, '只有管理员账号可以访问管理端')
    raise ApiError(403, '无权访问管理端')


# ---------------- 路由处理函数 ----------------

def h_bootstrap(ctx):
    return {
        'build': 'v5-202610311330',
        'llm': llm.available(),
        'auth': auth.enabled(),
        'admin': _admin_meta(ctx),
        'subjects': knowledge.subjects(),
        'writing_prompts': english.list_prompts(),
        'translation_items': english.list_translation_items(),
        'rubric_writing': english.rubric_writing(),
        'rubric_translation': english.rubric_translation(),
    }


def h_students_list(ctx):
    if auth.enabled():
        prof = store.get_profile(ctx['sid']) or {}
        s = store.get_student_summary(ctx['sid']) or {'id': ctx['sid'], 'name': prof.get('name') or '我的档案',
                                                      'created_at': prof.get('created_at'), 'kp_count': 0,
                                                      'avg_by_subject': {}, 'stats': prof.get('stats', {})}
        return {'students': [s]}
    idx = store.list_students()
    out = []
    for sid, info in idx.items():
        s = store.get_student_summary(sid)
        if s:
            out.append(s)
    return {'students': out}


def h_students_create(ctx):
    if auth.enabled():
        raise ApiError(403, '云端模式下注册账号即创建档案，无需新建')
    name = (ctx['body'] or {}).get('name', '').strip()
    sid, _ = store.create_student(name)
    return {'id': sid, 'summary': store.get_student_summary(sid)}


def _auth_register(ctx):
    b = ctx['body'] or {}
    try:
        uid, name = auth.register(b.get('name'), b.get('password'))
    except ValueError as e:
        raise ApiError(400, str(e))
    return {'token': auth.make_token(uid), 'uid': uid, 'name': name}


def _auth_login(ctx):
    b = ctx['body'] or {}
    try:
        uid, name = auth.login(b.get('name'), b.get('password'))
    except ValueError as e:
        raise ApiError(400, str(e))
    return {'token': auth.make_token(uid), 'uid': uid, 'name': name}


def _dashboard(ctx):
    sid = ctx['sid']
    summary = store.get_student_summary(sid)
    if not summary:
        raise ApiError(404, '学生不存在')
    weak = knowledge.weak_kps(sid, top=8)
    for w in weak:
        kp = knowledge.get_kp(w['subject'], w['id'])
        w['name'] = kp['name'] if kp else w['id']
    history = [h for h in store.get_history(sid, limit=400)
               if h.get('type') in ('qa', 'quiz', 'paper_grade', 'english', 'reflect', 'material')][-15:][::-1]
    mem = memory.get_memory(sid)
    pstats = points.stats(points.load(sid))
    # plan/review 摘要不再同步返回（偶发慢会拖住首屏），前端异步填充两张卡
    return {'summary': summary, 'weak': weak, 'history': history, 'memory': mem,
            'llm': llm.available(),
            'points': {k: pstats[k] for k in ('balance', 'today', 'week', 'streak', 'goal', 'weekGoal')}}


def _knowledge(ctx):
    sid, subject = ctx['sid'], ctx['query'].get('subject', 'linear_algebra')
    sub = knowledge.get_subject(subject)
    if not sub:
        raise ApiError(404, '未知科目')
    m = store.mastery_levels(sid)
    tree = []
    for kp in knowledge.kp_tree(subject):
        rec = m.get(kp['id'])
        score = rec['score'] if rec else None
        tree.append({
            'id': kp['id'], 'name': kp['name'], 'prereqs': kp['prereqs'],
            'description': kp['description'], 'key_points': kp['key_points'],
            'common_errors': kp['common_errors'],
            'sample': kp['samples'][0] if kp['samples'] else None,
            'samples': kp['samples'],
            'score': score, 'level': knowledge.level_of(score) if score is not None else '未诊断',
        })
    return {'subject': subject, 'name': sub['name'], 'kps': tree,
            'subjects': knowledge.subjects()}


def _english_prompts(ctx):
    return {'prompts': english.list_prompts(ctx['query'].get('level') or None)}


def _english_translations(ctx):
    return {'items': english.list_translation_items(ctx['query'].get('level') or None)}


def _vocab_quiz(ctx):
    b = ctx['body'] or {}
    return vocab.quiz(ctx['sid'], level=b.get('level', 'cet4'),
                      count=b.get('count', 10), use_llm_sentences=bool(b.get('llm_sentences')))


def _vocab_submit(ctx):
    b = ctx['body'] or {}
    return vocab.submit(ctx['sid'], b.get('quiz_id'), b.get('answers', {}))


def _vocab_wordbook(ctx):
    return {'words': vocab.wordbook(ctx['sid'], ctx['query'].get('level') or None)}


def _vocab_word(ctx):
    info = vocab.word_info(ctx['sid'], ctx['query'].get('word', ''))
    if not info:
        raise ApiError(404, '词库中未找到该单词')
    return info


def _paper_generate(ctx):
    b = ctx['body'] or {}
    return paper.generate(ctx['sid'], b.get('subject', 'linear_algebra'),
                          kp_ids=b.get('kp_ids') or None,
                          difficulty=b.get('difficulty', 'mid'),
                          counts=b.get('counts') or {})


def _paper_list(ctx):
    return {'papers': store.list_papers(ctx['sid'])}


def _paper_get(ctx):
    p = store.get_paper(ctx['sid'], ctx['query'].get('id', ''))
    if not p:
        raise ApiError(404, '试卷不存在')
    return _public(p)


def _public(p):
    return {k: v for k, v in p.items() if k != 'offline'} | {'offline': p.get('offline', False)}


def _paper_submit(ctx):
    b = ctx['body'] or {}
    return paper.submit(ctx['sid'], b.get('paper_id'), b.get('answers', {}))


def _notes_generate(ctx):
    b = ctx['body'] or {}
    return notes.generate(ctx['sid'], b.get('subject', 'linear_algebra'),
                          kp_ids=b.get('kp_ids'),
                          include_materials=bool(b.get('include_materials', True)))


def _notes_list(ctx):
    return {'notes': store.list_notes(ctx['sid'])}


def _notes_get(ctx):
    n = store.get_note(ctx['sid'], ctx['query'].get('id', ''))
    if not n:
        raise ApiError(404, '讲义不存在')
    return n


def _materials_list(ctx):
    return {'materials': store.list_materials(ctx['sid'])}


def _materials_add(ctx):
    if ctx['files']:
        results = []
        for fname, data in ctx['files']:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ('.txt', '.md', '.docx', '.pdf'):
                results.append({'name': fname, 'error': '仅支持 .txt/.md/.docx/.pdf'})
                continue
            if ext == '.pdf':
                # 纯标准库解析 PDF 文本层；扫描件/加密件会给出具体原因
                try:
                    text = pdftext.extract(data)
                except ValueError as e:
                    results.append({'name': fname, 'error': str(e)})
                    continue
                r = materials.add_material(ctx['sid'], os.path.splitext(fname)[0], text)
                results.append(r or {'name': fname, 'error': 'PDF 里没有可用的文字内容'})
                continue
            r = materials.add_material(ctx['sid'], os.path.splitext(fname)[0], None, raw_docx=data if ext == '.docx' else None)
            if r is None and ext != '.docx':
                r = materials.add_material(ctx['sid'], fname, data.decode('utf-8', 'replace'))
            results.append(r or {'name': fname, 'error': '无法解析内容'})
        return {'results': results}
    b = ctx['body'] or {}
    text = (b.get('text') or '').strip()
    if len(text) < 20:
        raise ApiError(400, '资料内容太短（至少20字）')
    r = materials.add_material(ctx['sid'], b.get('name', '未命名资料'), text)
    if not r:
        raise ApiError(400, '资料解析失败')
    return r


def _materials_delete(ctx):
    ok = store.delete_material(ctx['sid'], ctx['query'].get('id', ''))
    if not ok:
        raise ApiError(404, '资料不存在')
    return {'ok': True}


def _materials_search(ctx):
    b = ctx['body'] or {}
    return {'chunks': materials.retrieve(ctx['sid'], b.get('query', ''), top=4)}


def _memory_get(ctx):
    return memory.get_memory(ctx['sid'])


def _memory_pref_add(ctx):
    b = ctx['body'] or {}
    ok = memory.add_preference(ctx['sid'], b.get('text', ''))
    if not ok:
        raise ApiError(400, '指令不能为空')
    return memory.get_memory(ctx['sid'])


def _memory_pref_del(ctx):
    b = ctx['body'] or {}
    memory.remove_preference(ctx['sid'], b.get('text', ''))
    return memory.get_memory(ctx['sid'])


def _memory_reflect(ctx):
    res = memory.reflect(ctx['sid'])
    if res is None:
        raise ApiError(404, '学生不存在')
    return res


def _feedback(ctx):
    b = ctx['body'] or {}
    rating = int(b.get('rating', 0))
    ok = memory.add_feedback(ctx['sid'], b.get('module', ''), b.get('target', ''),
                             rating, b.get('comment', ''))
    if not ok:
        raise ApiError(400, '反馈保存失败')
    metrics.record_feedback(ctx['sid'], rating, b.get('module', ''), b.get('comment', ''))
    memory.refresh_system_async()  # 全员策略过期时后台自动重学
    return {'ok': True}


# ---------- 全员反馈学习（系统级） ----------

def _system_insight(ctx):
    doc = memory.get_system()
    ins = memory.global_insight()
    return {'strategy': doc.get('text', ''), 'updated': doc.get('updated'),
            'insight': doc.get('insight') or {k: ins[k] for k in ('users', 'feedback_n')},
            'live': {'users': ins['users'], 'feedback_n': ins['feedback_n'],
                     'neg_feedback': ins['neg_feedback'], 'weak_top': ins['weak_top'],
                     'questions_recent': ins['questions_recent'][:8]}}


def _system_reflect(ctx):
    doc = memory.reflect_system(force=True)
    return {'strategy': doc.get('text', ''), 'updated': doc.get('updated'),
            'insight': doc.get('insight') or {}}


def _system_strategy(ctx):
    b = ctx['body'] or {}
    doc = memory.set_system_strategy(b.get('text', ''))
    return {'strategy': doc.get('text', ''), 'updated': doc.get('updated')}


# ---------- 外部AI 引导（借力模式） ----------

def _external_prompt(ctx):
    b = ctx['body'] or {}
    try:
        return external.build_prompt(ctx['sid'], b.get('question', ''),
                                     subject=b.get('subject') or None, mode=b.get('mode', 'guide'))
    except ValueError as e:
        raise ApiError(400, str(e))


def _external_save(ctx):
    b = ctx['body'] or {}
    try:
        return external.save_answer(ctx['sid'], b.get('question', ''), b.get('subject') or None,
                                    b.get('answer', ''), model_used=b.get('model', ''))
    except ValueError as e:
        raise ApiError(400, str(e))


def _external_list(ctx):
    return external.list_items(ctx['sid'])


def _external_get(ctx):
    it = external.get_item(ctx['sid'], (ctx['query'] or {}).get('id', ''))
    if not it:
        raise ApiError(404, '记录不存在')
    return it


def _external_delete(ctx):
    b = ctx['body'] or {}
    if not external.remove_item(ctx['sid'], b.get('id', '')):
        raise ApiError(404, '记录不存在')
    return external.list_items(ctx['sid'])


# ---------- 学习计划（定路线） ----------

def _plan_get(ctx):
    return {'plan': plan.get(ctx['sid'])}


def _plan_create(ctx):
    b = ctx['body'] or {}
    try:
        return {'plan': plan.create(ctx['sid'], b.get('subject', ''), b.get('goal', ''),
                                    b.get('exam_date', ''), b.get('daily_minutes', 40),
                                    b.get('level', 'review'))}
    except ValueError as e:
        raise ApiError(400, str(e))


def _plan_done(ctx):
    b = ctx['body'] or {}
    try:
        result, awarded = plan.mark_done(ctx['sid'], b.get('day', 0), b.get('score'))
    except ValueError as e:
        raise ApiError(400, str(e))
    return {'plan': result, 'awarded': awarded}


def _plan_delete(ctx):
    if not plan.delete(ctx['sid']):
        raise ApiError(404, '没有学习计划')
    return {'ok': True}


# ---------- 每日课程（阶段二） ----------

def _daily_summary(ctx):
    q = ctx['query'] or {}
    try:
        return daily.summary(ctx['sid'], int(q['day']) if q.get('day') else None)
    except (ValueError, TypeError):
        return daily.summary(ctx['sid'])


def _daily_generate(ctx):
    b = ctx['body'] or {}
    try:
        return daily.generate(ctx['sid'], int(b.get('day', 0)))
    except (ValueError, TypeError) as e:
        raise ApiError(400, str(e))


def _daily_get(ctx):
    q = ctx['query'] or {}
    course = daily.get(ctx['sid'], int(q.get('day', 0)))
    if not course:
        raise ApiError(404, '该天课程尚未生成')
    return course


# ---------- 大学数学题库 + 组卷工作台 ----------

def _bank_capabilities(ctx):
    return bank.capabilities()


def _bank_search(ctx):
    q = ctx['query'] or {}
    return bank.search(subject=q.get('subject') or None, kp=q.get('kp') or None,
                       qtype=q.get('type') or None, difficulty=q.get('difficulty') or None,
                       q=q.get('q', ''), page=q.get('page', 1), size=q.get('size', 20))


def _bank_item(ctx):
    q = ctx['query'] or {}
    it = bank.get_item(q.get('id', ''))
    if not it:
        raise ApiError(404, '题目不存在')
    return it


def _bank_add(ctx):
    try:
        return {'id': bank.add(ctx['body'] or {})}
    except ValueError as e:
        raise ApiError(400, str(e))


def _bank_update(ctx):
    b = ctx['body'] or {}
    try:
        return {'id': bank.update(b.get('id', ''), b)}
    except ValueError as e:
        raise ApiError(400, str(e))


def _bank_delete(ctx):
    b = ctx['body'] or {}
    try:
        bank.delete(b.get('id', ''))
    except ValueError as e:
        raise ApiError(404, str(e))
    return {'ok': True}


def _bank_compose(ctx):
    b = ctx['body'] or {}
    try:
        return bank.compose(b.get('subject', 'linear_algebra'), kp_ids=b.get('kp_ids') or None,
                            counts=b.get('counts') or {}, duration=b.get('duration', 90),
                            title=b.get('title', ''), seed=b.get('seed'))
    except ValueError as e:
        raise ApiError(400, str(e))


def _bank_to_paper(ctx):
    b = ctx['body'] or {}
    try:
        paper = bank.to_paper(ctx['sid'], b.get('draft') or {})
    except ValueError as e:
        raise ApiError(400, str(e))
    return {'paper_id': paper['id'], 'paper': paper}


# ---------- 任务积分 ----------

def _points_get(ctx):
    return points.full_state(ctx['sid'])


def _points_task_add(ctx):
    b = ctx['body'] or {}
    t = points.add_task(ctx['sid'], b)
    if not t:
        raise ApiError(400, '任务内容不能为空')
    return points.full_state(ctx['sid'])


def _points_task_toggle(ctx):
    b = ctx['body'] or {}
    t, err = points.toggle_task(ctx['sid'], b.get('id', ''))
    if err:
        raise ApiError(400, err)
    return points.full_state(ctx['sid'])


def _points_task_delete(ctx):
    b = ctx['body'] or {}
    if not points.delete_task(ctx['sid'], b.get('id', '')):
        raise ApiError(404, '任务不存在')
    return points.full_state(ctx['sid'])


def _points_reward_add(ctx):
    b = ctx['body'] or {}
    if not points.add_reward(ctx['sid'], b):
        raise ApiError(400, '奖励名称不能为空')
    return points.full_state(ctx['sid'])


def _points_reward_update(ctx):
    b = ctx['body'] or {}
    r = points.update_reward(ctx['sid'], b.get('id', ''), b.get('k'), b.get('v'))
    if not r:
        raise ApiError(404, '奖励不存在')
    return points.full_state(ctx['sid'])


def _points_redeem(ctx):
    b = ctx['body'] or {}
    r, err = points.redeem(ctx['sid'], b.get('id', ''))
    if err:
        raise ApiError(400, err)
    return points.full_state(ctx['sid'])


def _points_reward_delete(ctx):
    b = ctx['body'] or {}
    points.delete_reward(ctx['sid'], b.get('id', ''))
    return points.full_state(ctx['sid'])


def _points_unspend(ctx):
    b = ctx['body'] or {}
    points.undo_spent(ctx['sid'], b.get('id', ''))
    return points.full_state(ctx['sid'])


def _points_cats(ctx):
    b = ctx['body'] or {}
    err = points.cats_op(ctx['sid'], b.get('op', 'add'), b.get('name', ''))
    if err:
        raise ApiError(400, err)
    return points.full_state(ctx['sid'])


def _points_settings(ctx):
    b = ctx['body'] or {}
    points.settings(ctx['sid'], goal=b.get('goal'), week_goal=b.get('weekGoal'))
    return points.full_state(ctx['sid'])


def _points_import(ctx):
    b = ctx['body'] or {}
    res, err = points.import_backup(ctx['sid'], b.get('data'))
    if err:
        raise ApiError(400, err)
    return points.full_state(ctx['sid']) | {'imported': res}


def _points_makeup(ctx):
    res, err = points.makeup(ctx['sid'])
    if err:
        raise ApiError(400, err)
    return points.full_state(ctx['sid'])


def _points_simulate(ctx):
    points.simulate_day(ctx['sid'])
    return points.full_state(ctx['sid'])


# ---------- API 接入窗口 ----------

def _clean_fallback(items):
    """校验并规整前端传来的兜底链：[{base_url, model, vision_model, api_key?}]"""
    out = []
    for it in (items or [])[:8]:                 # 最多 8 条，防止前端乱塞
        if not isinstance(it, dict):
            continue
        base = (it.get('base_url') or '').strip()
        if not base.startswith(('http://', 'https://')):
            continue
        row = {'base_url': base.rstrip('/'),
               'model': (it.get('model') or '').strip()[:80],
               'vision_model': (it.get('vision_model') or '').strip()[:80]}
        key = (it.get('api_key') or '').strip()
        if key:
            row['api_key'] = key
        out.append(row)
    return out


def _config_get(ctx):
    cfg = llm.load_config()
    l = cfg['llm']
    s = cfg.get('search', {})
    fb = []
    for it in (l.get('fallback') or []):
        if isinstance(it, dict) and it.get('base_url'):
            fb.append({'base_url': it.get('base_url', ''),
                       'model': it.get('model', ''),
                       'vision_model': it.get('vision_model', ''),
                       'has_key': bool(it.get('api_key'))})
    return {'llm': {'base_url': l.get('base_url', ''), 'model': l.get('model', ''),
                    'vision_model': l.get('vision_model', ''), 'has_key': bool(l.get('api_key')),
                    'key_masked': llm.mask_key(l.get('api_key', '')),
                    'fallback': fb},
            'search': {'provider': s.get('provider', ''), 'has_key': bool(s.get('api_key'))},
            'llm_available': llm.available(), 'vision_available': llm.vision_available(),
            'channels': llm.channel_status()}   # 主通道 + 免费兜底链的实时状态（含熔断剩余秒数）


def _config_save(ctx):
    """保存到当前账号（云端按 uid 隔离 / 本地按档案隔离），不影响系统默认与他人。"""
    b = ctx['body'] or {}
    nl = b.get('llm') or {}
    llm_fields = {}
    for k in ('base_url', 'model', 'vision_model', 'stream_url'):
        if nl.get(k):
            llm_fields[k] = nl[k].strip()
    if nl.get('api_key'):
        llm_fields['api_key'] = nl['api_key'].strip()
    # 兜底链：前端可视化编辑后整条覆盖（空数组 = 关闭兜底）
    if isinstance(nl.get('fallback'), list):
        llm_fields['fallback'] = _clean_fallback(nl['fallback'])
    # SSRF 防护：云端多用户模式下，学生配置的所有请求地址（主通道/流式/兜底链）
    # 均不得指向内网或本机地址（本地单机模式不受影响，允许访问本地 Ollama 等）
    if auth.enabled():
        from urllib.parse import urlparse
        candidates = [llm_fields.get('base_url', ''), llm_fields.get('stream_url', '')] \
            + [f.get('base_url', '') for f in llm_fields.get('fallback', [])]
        for u in candidates:
            if u and llm._host_private(urlparse(u).hostname or ''):
                raise ApiError(400, '安全限制：云端模式不允许将 AI 请求指向内网或本机地址（%s）' % urlparse(u).hostname)
    ns = b.get('search') or {}
    search_fields = {}
    if 'provider' in ns and ns.get('provider') is not None:
        search_fields['provider'] = ns['provider'].strip()
    if ns.get('api_key'):
        search_fields['api_key'] = ns['api_key'].strip()
    llm.save_user_config(ctx['sid'], llm_fields, search_fields)
    return _config_get(ctx)


def _config_test(ctx):
    """测试大模型连通性（发一条极小消息；失败信息里会列出各通道的结果）。"""
    try:
        out = llm.chat([{'role': 'user', 'content': '请只回复：OK'}], temperature=0, timeout=30, max_tokens=10)
        return {'ok': True, 'reply': (out or '').strip()[:30], 'channel': llm.last_channel(),
                'channels': llm.channel_status()}
    except llm.LLMError as e:
        return {'ok': False, 'error': str(e)[:300], 'channels': llm.channel_status()}


# ---------- 图片附件 ----------

def _upload_image(ctx):
    if not ctx['files']:
        raise ApiError(400, '没有收到图片文件')
    results = []
    for fname, data in ctx['files']:
        ext = os.path.splitext(fname)[1].lower().lstrip('.')
        if ext not in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
            results.append({'name': fname, 'error': '仅支持 png/jpg/jpeg/webp/gif'})
            continue
        if len(data) > 8 * 1024 * 1024:
            results.append({'name': fname, 'error': '图片超过 8MB'})
            continue
        name = store.save_image(ctx['sid'], data, ext)
        results.append({'name': fname, 'file': name, 'url': '/api/img?sid=%s&file=%s' % (ctx['sid'], name)})
    return {'results': results}


def _upload_extract(ctx):
    """作文/翻译文档抽取：.txt/.md/.docx → 文本（供批改）；图片 → 存为附件。"""
    if not ctx['files']:
        raise ApiError(400, '没有收到文件')
    fname, data = ctx['files'][0]
    ext = os.path.splitext(fname)[1].lower()
    if ext in ('.txt', '.md'):
        text = data.decode('utf-8', 'replace')
    elif ext == '.docx':
        text = materials._extract_docx(data)
    elif ext.lstrip('.') in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
        name = store.save_image(ctx['sid'], data, ext)
        return {'kind': 'image', 'file': name, 'url': '/api/img?sid=%s&file=%s' % (ctx['sid'], name), 'name': fname}
    else:
        raise ApiError(400, '仅支持 .txt/.md/.docx 文档或图片')
    text = (text or '').strip()
    if len(text) < 20:
        raise ApiError(400, '文档内容太短或无法解析')
    return {'kind': 'doc', 'text': text[:20000], 'name': fname}


def _wrongbook(ctx):
    return wrongbook.grouped(ctx['sid'])


def _wrongbook_variants(ctx):
    b = ctx['body'] or {}
    try:
        vs = wrongbook.generate_variants(ctx['sid'], b.get('id', ''))
    except ValueError as e:
        raise ApiError(404, str(e))
    return {'id': b.get('id', ''), 'variants': vs}


def _wrongbook_practice(ctx):
    b = ctx['body'] or {}
    try:
        r = wrongbook.submit_practice(ctx['sid'], b.get('id', ''), int(b.get('idx', 0)),
                                      b.get('answer', ''), self_correct=b.get('self_correct'))
    except (ValueError, TypeError) as e:
        raise ApiError(400, str(e))
    return r


def _wrongbook_resolve(ctx):
    b = ctx['body'] or {}
    n, reason = wrongbook.resolve(ctx['sid'], b.get('id', ''), bool(b.get('resolved', True)),
                                  force=bool(b.get('force')))
    if not n:
        if reason:
            raise ApiError(400, reason)
        raise ApiError(404, '错题不存在')
    return wrongbook.grouped(ctx['sid'])


def _weekly(ctx):
    return weekly.build(ctx['sid'])


# ---------------- 管理端接口 ----------------

def _admin_whoami(ctx):
    """不抛错，只回答「当前请求者是不是管理员」——前端用它决定是否显示入口。"""
    return _admin_meta(ctx)


def _admin_overview(ctx):
    _admin_guard(ctx)
    return admin.overview()


def _admin_daily(ctx):
    _admin_guard(ctx)
    days = int(ctx.get('query', {}).get('days') or 30)
    return {'days': admin.daily(max(1, min(days, 365)))}


def _admin_users(ctx):
    _admin_guard(ctx)
    return {'users': admin.users(), 'weak': admin.weak_top(10)}


def _admin_longterm(ctx):
    _admin_guard(ctx)
    return admin.longterm()


def _admin_ai_summary(ctx):
    _admin_guard(ctx)
    return admin.ai_summary()


def _admin_prune(ctx):
    _admin_guard(ctx)
    n = int(ctx.get('body', {}).get('days') or 90)
    return {'removed': metrics.prune(n)}


def _archive_status(ctx):
    return archive.status()

def _archive_run(ctx):
    """手动触发一次归档（免费容器平台可用它替代 cron）。"""
    r = archive.run_once()
    if not archive.enabled():
        raise ApiError(400, r.get('detail') or '未配置归档目标')
    return r


def _backup_zip():
    """把 data/db/ 全部学生数据打包为 zip 字节流（config 不含，避免泄露 Key）。"""
    import io
    import zipfile
    buf = io.BytesIO()
    root = os.path.join(store.BASE, 'data', 'db')
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, os.path.join(store.BASE, 'data'))
                try:
                    with open(full, 'rb') as f:
                        z.writestr('zhiyuan-backup/' + rel, f.read())
                except OSError:
                    continue
    return buf.getvalue()


def _sources(ctx):
    return {'sources': search.all_sources()}


def _memory_fb_update(ctx):
    b = ctx['body'] or {}
    ok = memory.update_feedback(ctx['sid'], float(b.get('ts', 0)),
                                rating=b.get('rating'), comment=b.get('comment'))
    if not ok:
        raise ApiError(404, '反馈记录不存在')
    return memory.get_memory(ctx['sid'])


def _memory_fb_delete(ctx):
    b = ctx['body'] or {}
    if not memory.delete_feedback(ctx['sid'], float(b.get('ts', 0))):
        raise ApiError(404, '反馈记录不存在')
    return memory.get_memory(ctx['sid'])


def _memory_strategy(ctx):
    b = ctx['body'] or {}
    if not memory.set_strategy(ctx['sid'], b.get('text', '')):
        raise ApiError(404, '学生不存在')
    return memory.get_memory(ctx['sid'])


# ---------- 问答/批改（支持图片） ----------

def _load_image(ctx):
    """body.image 为已上传图片文件名；返回 (bytes, mime) 或 None"""
    name = (ctx['body'] or {}).get('image')
    if not name:
        return None
    data, mime = store.get_image(ctx['sid'], name)
    if not data:
        raise ApiError(404, '图片不存在或已过期')
    return data, mime


def _qa(ctx):
    b = ctx['body'] or {}
    q = (b.get('question') or '').strip()
    image = _load_image(ctx)
    if not q and not image:
        raise ApiError(400, '问题不能为空')
    # 旧 sid（换了浏览器/档案被删）先给出明确提示，而不是一路走到 500
    sid = ctx['sid']
    if sid and sid not in store.list_students():
        raise ApiError(400, '学习档案不存在（可能是浏览器里的旧缓存），请刷新页面后重试')
    r = qa.answer(ctx['sid'], q, subject=b.get('subject') or None,
                  mode=b.get('mode', 'guide'), image=image,
                  use_web=bool(b.get('use_web', True)))
    if r.get('error'):
        raise ApiError(400, r.get('message', r['error']))
    r['channel'] = llm.last_channel()   # 本次由哪条通道生成（含免费兜底）
    return r


def _english_grade(ctx):
    b = ctx['body'] or {}
    text = (b.get('text') or '').strip()
    image = _load_image(ctx)
    if len(text) < 10 and not image:
        raise ApiError(400, '答案太短，无法批改')
    try:
        r = english.grade(ctx['sid'], b.get('kind', 'writing'), text,
                          level=b.get('level', 'cet4'), prompt_id=b.get('prompt_id'), image=image)
    except ValueError as e:
        raise ApiError(400, str(e))
    if r.get('error'):
        raise ApiError(400, r.get('message', r['error']))
    return r


ROUTES = {
    ('GET', 'bootstrap'): h_bootstrap,
    ('GET', 'config'): _config_get,
    ('POST', 'config'): _config_save,
    ('POST', 'config/test'): _config_test,
    ('POST', 'upload/image'): _upload_image,
    ('POST', 'upload/extract'): _upload_extract,
    ('GET', 'sources'): _sources,
    ('GET', 'wrongbook'): _wrongbook,    ('POST', 'wrongbook/variants'): _wrongbook_variants,
    ('POST', 'wrongbook/practice'): _wrongbook_practice,
    ('POST', 'wrongbook/resolve'): _wrongbook_resolve,
    ('GET', 'weekly'): _weekly,
    ('GET', 'archive/status'): _archive_status,
    ('POST', 'archive/run'): _archive_run,
    # 管理端（看用户数/调用数/反馈数/长期总结）
    ('GET', 'admin/whoami'): _admin_whoami,
    ('GET', 'admin/overview'): _admin_overview,
    ('GET', 'admin/daily'): _admin_daily,
    ('GET', 'admin/users'): _admin_users,
    ('GET', 'admin/longterm'): _admin_longterm,
    ('POST', 'admin/ai-summary'): _admin_ai_summary,
    ('POST', 'admin/prune'): _admin_prune,
    ('GET', 'students'): h_students_list,
    ('POST', 'students'): h_students_create,
    ('POST', 'auth/register'): _auth_register,
    ('POST', 'auth/login'): _auth_login,
    ('GET', 'dashboard'): _dashboard,
    ('GET', 'knowledge'): _knowledge,
    ('POST', 'qa'): _qa,
    ('GET', 'english/prompts'): _english_prompts,
    ('GET', 'english/translations'): _english_translations,
    ('POST', 'english/grade'): _english_grade,
    ('POST', 'vocab/quiz'): _vocab_quiz,
    ('POST', 'vocab/submit'): _vocab_submit,
    ('GET', 'vocab/wordbook'): _vocab_wordbook,
    ('GET', 'vocab/word'): _vocab_word,
    ('POST', 'paper/generate'): _paper_generate,
    ('GET', 'paper/list'): _paper_list,
    ('GET', 'paper'): _paper_get,
    ('POST', 'paper/submit'): _paper_submit,
    ('POST', 'notes/generate'): _notes_generate,
    ('GET', 'notes/list'): _notes_list,
    ('GET', 'notes'): _notes_get,
    ('GET', 'materials'): _materials_list,
    ('POST', 'materials'): _materials_add,
    ('DELETE', 'materials'): _materials_delete,
    ('POST', 'materials/search'): _materials_search,
    ('GET', 'memory'): _memory_get,
    ('POST', 'memory/preference'): _memory_pref_add,
    ('POST', 'memory/preference/delete'): _memory_pref_del,
    ('POST', 'memory/feedback/update'): _memory_fb_update,
    ('POST', 'memory/feedback/delete'): _memory_fb_delete,
    ('POST', 'memory/strategy'): _memory_strategy,
    ('POST', 'memory/reflect'): _memory_reflect,
    ('POST', 'feedback'): _feedback,
    ('GET', 'system/insight'): _system_insight,
    ('POST', 'system/reflect'): _system_reflect,
    ('POST', 'system/strategy'): _system_strategy,
    ('POST', 'external/prompt'): _external_prompt,
    ('POST', 'external/save'): _external_save,
    ('GET', 'external'): _external_list,
    ('GET', 'external/item'): _external_get,
    ('DELETE', 'external/item'): _external_delete,
    ('GET', 'plan'): _plan_get,
    ('POST', 'plan/create'): _plan_create,
    ('POST', 'plan/done'): _plan_done,
    ('POST', 'plan/delete'): _plan_delete,
    ('GET', 'daily'): _daily_summary,
    ('POST', 'daily/generate'): _daily_generate,
    ('GET', 'daily/course'): _daily_get,
    ('GET', 'review/due'): lambda ctx: wrongbook.due_review(ctx['sid']),
    ('GET', 'bank/capabilities'): _bank_capabilities,
    ('GET', 'bank/search'): _bank_search,
    ('GET', 'bank/item'): _bank_item,
    ('POST', 'bank/add'): _bank_add,
    ('POST', 'bank/update'): _bank_update,
    ('POST', 'bank/delete'): _bank_delete,
    ('POST', 'bank/compose'): _bank_compose,
    ('POST', 'bank/to_paper'): _bank_to_paper,
    ('GET', 'points'): _points_get,
    ('POST', 'points/task'): _points_task_add,
    ('POST', 'points/task/toggle'): _points_task_toggle,
    ('POST', 'points/task/delete'): _points_task_delete,
    ('POST', 'points/reward'): _points_reward_add,
    ('POST', 'points/reward/update'): _points_reward_update,
    ('POST', 'points/reward/redeem'): _points_redeem,
    ('POST', 'points/reward/delete'): _points_reward_delete,
    ('POST', 'points/spent/undo'): _points_unspend,
    ('POST', 'points/cats'): _points_cats,
    ('POST', 'points/settings'): _points_settings,
    ('POST', 'points/import'): _points_import,
    ('POST', 'points/makeup'): _points_makeup,
    ('POST', 'points/simulate'): _points_simulate,
}


# ---------------- 请求处理器 ----------------

class Handler(BaseHTTPRequestHandler):
    server_version = 'ZhiYuanStudy/1.0'

    def log_message(self, fmt, *args):  # 精简控制台日志
        pass

    # -- 工具 --
    def _send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # 客户端提前断开（刷新/取消），忽略

    def _serve_static(self, path):
        if path in ('/', '/index.html'):
            path = '/index.html'
        fp = os.path.normpath(os.path.join(FRONTEND, path.lstrip('/')))
        # 路径穿越防护：必须落在 FRONTEND 目录内部（带分隔符校验，防止同名前缀目录绕过）
        if fp != FRONTEND and not fp.startswith(FRONTEND + os.sep) or not os.path.isfile(fp):
            self._send_json(404, {'error': 'Not Found'})
            return
        ctype = mimetypes.guess_type(fp)[0] or 'application/octet-stream'
        # ETag + 304：app.js 有 138 KB，之前用 no-store 导致每次打开都重传。
        # 改成「可缓存但每次校验」，未变更时只回 304 头（约 100 字节），
        # 既省流量（对 ngrok 免费额度/流量敏感的场景很关键）又不影响发版后立即生效。
        st = os.stat(fp)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith('text/') else ''))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('ETag', etag)
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # 客户端提前断开（刷新/取消），忽略

    def _parse_multipart(self):
        ctype = self.headers.get('Content-Type', '')
        m = re.search(r'boundary=([^;]+)', ctype)
        if not m:
            return [], []
        boundary = m.group(1).strip('"').encode()
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        files, fields = [], []
        for part in body.split(b'--' + boundary):
            part = part.strip(b'\r\n')
            if not part or part == b'--':
                continue
            if b'\r\n\r\n' not in part:
                continue
            head, _, content = part.partition(b'\r\n\r\n')
            head = head.decode('utf-8', 'replace')
            name_m = re.search(r'name="([^"]*)"', head)
            file_m = re.search(r'filename="([^"]*)"', head)
            if file_m:
                files.append((file_m.group(1), content))
            elif name_m:
                fields.append((name_m.group(1), content.decode('utf-8', 'replace')))
        return files, fields

    def _read_body(self):
        ctype = self.headers.get('Content-Type', '')
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length > MAX_BODY:
            raise ApiError(413, '请求体过大（上限 64MB）')
        if 'multipart/form-data' in ctype:
            files, fields = self._parse_multipart()
            body = {k: v for k, v in fields}
            return body, files
        if length <= 0:
            return {}, []
        try:
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            return (data if isinstance(data, dict) else {}), []
        except ValueError:
            return {}, []

    def _serve_image(self, query):
        sid = query.get('sid', '')
        if not SID_RE.match(sid or ''):
            self._send_json(404, {'error': '图片不存在'})
            return
        data, mime = store.get_image(sid, query.get('file', ''))
        if not data:
            self._send_json(404, {'error': '图片不存在'})
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # 客户端提前断开（刷新/取消），忽略

    def _qa_stream(self):
        """POST /api/qa/stream —— SSE 流式问答。"""
        body, _files = self._read_body()
        sid = body.get('sid', '')
        if auth.enabled():
            tok = (self.headers.get('Authorization') or '')[7:].strip()
            uid = auth.verify_token(tok)
            if not uid:
                self._send_json(401, {'error': '请先登录'})
                return
            sid = uid
        q = (body.get('question') or '').strip()
        image = None
        name = body.get('image')
        if name:
            data, mime = store.get_image(sid, name)
            if data:
                image = (data, mime)
        if not q and not image:
            self._send_json(400, {'error': '问题不能为空'})
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        def emit(ev, data):
            try:
                self.wfile.write(('event: %s\ndata: %s\n\n' % (ev, json.dumps(data, ensure_ascii=False))).encode('utf-8'))
                self.wfile.flush()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                raise IOError('client gone')

        try:
            emit('meta', {'sid': sid})
            r = qa.answer_stream(sid, q, subject=body.get('subject') or None,
                                 mode=body.get('mode', 'guide'), image=image,
                                 use_web=bool(body.get('use_web', True)),
                                 on_delta=lambda t: emit('delta', {'t': t}))
            if r.get('error'):
                emit('error', {'message': r.get('message', r['error'])})
            else:
                r['channel'] = llm.last_channel()
                emit('final', r)
        except IOError:
            return
        except Exception as e:  # noqa: BLE001
            try:
                emit('error', {'message': str(e)[:200]})
            except Exception:
                pass

    def _dispatch(self, method):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.strip('/').split('/')
        if parts[0] == 'api':
            route_name = '/'.join(parts[1:])
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
            # 云端模式鉴权：bootstrap/注册/登录放行，管理端自带口令鉴权也放行，
            # 其余要求有效令牌并强制本人档案
            if auth.enabled() and not (
                    (method == 'GET' and route_name == 'bootstrap') or
                    (method == 'POST' and route_name in ('auth/register', 'auth/login')) or
                    route_name.startswith('admin/')):
                tok = (self.headers.get('Authorization') or '')[7:].strip()
                uid = auth.verify_token(tok)
                if not uid:
                    self._send_json(401, {'error': '请先登录'})
                    return
                query['sid'] = uid
            if method == 'GET' and route_name == 'img':
                self._serve_image(query)
                return
            if method == 'POST' and route_name == 'qa/stream':
                self._qa_stream()
                return
            if method == 'GET' and route_name == 'backup':
                import time as _time
                data = _backup_zip()
                fname = 'zhiyuan-backup-%s.zip' % _time.strftime('%Y%m%d-%H%M%S')
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename="%s"' % fname)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass
                return
            handler = ROUTES.get((method, route_name))
            if not handler:
                self._send_json(404, {'error': '未知接口: %s %s' % (method, route_name)})
                return
            if os.environ.get('ZY_DEBUG'):
                print('[dispatch] %s %s' % (method, route_name), file=sys.stderr, flush=True)
            try:
                body, files = self._read_body()   # 请求体过大时在此抛 413
                sid = query.get('sid') or (body.get('sid') if isinstance(body, dict) else '') or ''
                if sid and not SID_RE.match(sid):   # 路径穿越防护：sid 仅允许安全字符
                    sid = ''
                ctx = {'sid': sid, 'query': query, 'body': body, 'files': files,
                       'headers': self.headers,
                       'client_ip': (self.client_address or ('?',))[0]}
                llm.set_request_user(sid)   # 本请求的 LLM 配置按账号隔离（云端多用户 / 本地多档案通用）
                result = handler(ctx)
                if os.environ.get('ZY_DEBUG'):
                    print('[done] %s %s' % (method, route_name), file=sys.stderr, flush=True)
                self._send_json(200, result)
            except ApiError as e:
                self._send_json(e.status, {'error': e.msg})
            except Exception as e:  # noqa: BLE001 统一兜底
                import traceback
                traceback.print_exc()
                self._send_json(500, {'error': '服务器内部错误: %s' % e})
            finally:
                llm.clear_request_user()
            return
        if method == 'GET':
            self._serve_static(parsed.path)
        else:
            self._send_json(404, {'error': 'Not Found'})

    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def do_DELETE(self):
        self._dispatch('DELETE')
