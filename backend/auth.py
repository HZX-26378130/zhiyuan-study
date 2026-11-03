# -*- coding: utf-8 -*-
"""账号体系：用户名+密码注册登录（PBKDF2-SHA256），HMAC 无状态会话令牌。

仅当 ZY_AUTH=1 时启用（自托管公网部署 / 云端多用户），本地单机保持免登录。
账号存储走 store.user_*：云端模式写 PostgreSQL，自托管模式写 data/db/users.json。
"""
import hashlib
import hmac
import os
import time

from . import store

_TTL = 90 * 86400
_secret_cache = None


def _secret():
    """会话签名密钥。

    优先级：环境变量 ZY_SECRET → data/db/.secret（首次自动生成并落盘，重启后登录态不失效）
    → 兜底常量（仅保证不崩，公网部署务必设置 ZY_SECRET）。
    """
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    s = (os.environ.get('ZY_SECRET') or '').strip()
    if not s:
        path = store._path('.secret')
        try:
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    s = f.read().strip()
            if not s:
                s = hashlib.sha256(os.urandom(32)).hexdigest()
                d = os.path.dirname(path)
                if d and not os.path.isdir(d):
                    os.makedirs(d, exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(s)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        except OSError:
            s = ''
    _secret_cache = s or 'zhiyuan-local-secret'
    return _secret_cache


def enabled():
    return os.environ.get('ZY_AUTH') == '1'


def _pbkdf(password, salt_hex):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), 60000).hex()


def _sign(uid, exp):
    msg = ('%s.%d' % (uid, exp)).encode('utf-8')
    return hmac.new(_secret().encode('utf-8'), msg, hashlib.sha256).hexdigest()[:32]


def make_token(uid):
    exp = int(time.time()) + _TTL
    return '%s.%d.%s' % (uid, exp, _sign(uid, exp))


def verify_token(token):
    try:
        uid, exp, sig = str(token).split('.')
        exp = int(exp)
        if exp < time.time():
            return None
        if hmac.compare_digest(_sign(uid, exp), sig):
            return uid
    except (ValueError, TypeError):
        pass
    return None


def register(name, password):
    name = (name or '').strip()[:20]
    password = password or ''
    if len(name) < 2:
        raise ValueError('用户名至少 2 个字符')
    if len(password) < 6:
        raise ValueError('密码至少 6 位')
    if store.user_get(name):
        raise ValueError('用户名已被注册')
    uid = store.new_id()
    salt = os.urandom(16).hex()
    store.user_add(uid, name, salt, _pbkdf(password, salt))
    store.init_profile(uid, name)
    return uid, name


def login(name, password):
    doc = store.user_get((name or '').strip()[:20])
    if not doc:
        raise ValueError('用户不存在，请先注册')
    if not hmac.compare_digest(_pbkdf(password or '', doc['salt']), doc.get('hash', '')):
        raise ValueError('密码错误')
    uid = doc['uid']
    if not store.get_profile(uid):
        store.init_profile(uid, doc.get('name', name))
    return uid, doc.get('name', name)
