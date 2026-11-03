# -*- coding: utf-8 -*-
"""每日归档：把 data/db 快照「推出去」。

为什么需要它：Hugging Face Spaces / Koyeb / Render 这类免费容器平台的磁盘是
**临时的**，重新部署或休眠唤醒后 data/db 会被清空；而这些平台普遍没有可用的
cron（HF Spaces 没有定时任务，Render 的 Cron Job 要付费）。所以定时器只能跑在
应用进程里，并且备份必须主动推到外部存储。

启用（全部用环境变量，见 deploy/archive/README.md）：
    ZY_ARCHIVE_GITHUB_REPO=owner/repo     推送到私有 GitHub 仓库的目录
    ZY_ARCHIVE_GITHUB_TOKEN=ghp_xxx       （Fine-grained: Contents 读写）
    ZY_ARCHIVE_GITHUB_BRANCH=main         默认 main
    ZY_ARCHIVE_GITHUB_DIR=backups         默认 backups
    ZY_ARCHIVE_WEBHOOK=https://...        （可选）把 zip POST 给你的接收端
    ZY_ARCHIVE_INTERVAL_HOURS=24          默认 24；<=0 关闭定时器
    ZY_ARCHIVE_KEEP=7                     远端与本地各保留多少份
    ZY_ARCHIVE_LOCAL=0                    是否同时留本地副本（默认 1）
    ZY_ARCHIVE_GITHUB_API=https://api.github.com   （测试/企业版可改）

设计要点：
- 归档包里**不含 config.json**（避免把 API Key 传到外部仓库）
- 失败只记日志，绝不抛出到请求路径
- 同名文件覆盖式滚动 + 按名字时间排序裁剪，不需要额外索引文件
"""
import base64
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import store

ARCHIVE_SUBDIR = os.path.join('data', 'db', 'archive')
_last = {'ts': 0, 'ok': None, 'detail': '', 'name': '', 'bytes': 0}
_lock = threading.Lock()
_run_lock = threading.Lock()
_started = False


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def _cfg():
    return {
        'github_repo': _env('ZY_ARCHIVE_GITHUB_REPO'),
        'github_token': _env('ZY_ARCHIVE_GITHUB_TOKEN'),
        'github_branch': _env('ZY_ARCHIVE_GITHUB_BRANCH', 'main'),
        'github_dir': _env('ZY_ARCHIVE_GITHUB_DIR', 'backups').strip('/'),
        'github_api': _env('ZY_ARCHIVE_GITHUB_API', 'https://api.github.com').rstrip('/'),
        'webhook': _env('ZY_ARCHIVE_WEBHOOK'),
        'interval': float(_env('ZY_ARCHIVE_INTERVAL_HOURS', '24') or 24),
        'keep': int(_env('ZY_ARCHIVE_KEEP', '7') or 7),
        'local': (_env('ZY_ARCHIVE_LOCAL', '1') or '1') not in ('0', 'false', 'False'),
    }


def enabled():
    c = _cfg()
    return bool((c['github_repo'] and c['github_token']) or c['webhook'])


def snapshot_bytes():
    """把 data/db 打成 zip（排除 archive 自身，避免递归）。

    安全：额外排除含 API Key 的配置 —— 根级 config.json 与每个账号的 llm_config.json。
    归档通常推到管理员自己的仓库，不应把学生的 Key 一起搬过去；
    恢复后各人重新填一次 Key 即可，学习数据不受影响。
    """
    root = os.path.join(store.BASE, 'data', 'db')
    archive_root = os.path.join(store.BASE, ARCHIVE_SUBDIR)
    skip_names = {'config.json', 'llm_config.json'}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(root):
            if os.path.abspath(dirpath).startswith(os.path.abspath(archive_root)):
                continue
            for fn in files:
                if fn in skip_names:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                try:
                    with open(full, 'rb') as f:
                        z.writestr('zhiyuan-backup/' + rel.replace('\\', '/'), f.read())
                except OSError:
                    continue
    return buf.getvalue()


# ---------------- GitHub Contents API ----------------

def _gh(cfg, method, path, payload=None, timeout=60):
    url = cfg['github_api'] + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + cfg['github_token'],
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
        'User-Agent': 'zhiyuan-archive/1.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:300]


def _gh_path(cfg, name=''):
    parts = [cfg['github_dir']] + ([name] if name else [])
    seg = '/'.join(urllib.parse.quote(p, safe='') for p in parts if p)
    return '/repos/%s/contents/%s' % (cfg['github_repo'], seg)


def push_github(cfg, name, data):
    """上传（存在则覆盖），随后按保留份数裁剪旧包。返回说明字符串。"""
    path = _gh_path(cfg, name)
    q = '?ref=' + urllib.parse.quote(cfg['github_branch'])
    status, cur = _gh(cfg, 'GET', path + q)
    payload = {
        'message': 'archive: %s' % name,
        'content': base64.b64encode(data).decode('ascii'),
        'branch': cfg['github_branch'],
    }
    if status == 200 and isinstance(cur, dict) and cur.get('sha'):
        payload['sha'] = cur['sha']
    elif status not in (404, 200):
        return 'GitHub 查询失败 HTTP %s: %s' % (status, str(cur)[:150])

    status, res = _gh(cfg, 'PUT', path, payload)
    if status not in (200, 201):
        return 'GitHub 上传失败 HTTP %s: %s' % (status, str(res)[:150])

    removed = _prune_github(cfg)
    return 'GitHub 已上传%s' % ('，清理旧包 %d 个' % removed if removed else '')


def _prune_github(cfg):
    status, items = _gh(cfg, 'GET', _gh_path(cfg) + '?ref=' + urllib.parse.quote(cfg['github_branch']))
    if status != 200 or not isinstance(items, list):
        return 0
    files = [it for it in items if isinstance(it, dict) and str(it.get('name', '')).startswith('data-')
             and str(it.get('name', '')).endswith('.zip')]
    files.sort(key=lambda it: it['name'])
    removed = 0
    for old in files[:max(0, len(files) - cfg['keep'])]:
        st, _ = _gh(cfg, 'DELETE', _gh_path(cfg, old['name']), {
            'message': 'archive: prune %s' % old['name'],
            'sha': old['sha'],
            'branch': cfg['github_branch'],
        })
        if st in (200, 204):
            removed += 1
    return removed


# ---------------- 通用 webhook ----------------

def push_webhook(cfg, name, data, timeout=60):
    req = urllib.request.Request(cfg['webhook'], data=data, method='POST', headers={
        'Content-Type': 'application/zip',
        'X-Archive-Name': name,
        'User-Agent': 'zhiyuan-archive/1.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 'Webhook 已推送 HTTP %s' % r.status
    except urllib.error.HTTPError as e:
        return 'Webhook 失败 HTTP %s: %s' % (e.code, e.read()[:150].decode('utf-8', 'replace'))
    except Exception as e:  # noqa: BLE001
        return 'Webhook 失败: %s' % e


# ---------------- 本地副本 + 主流程 ----------------

def _save_local(name, data, keep):
    d = os.path.join(store.BASE, ARCHIVE_SUBDIR)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), 'wb') as f:
            f.write(data)
        olds = sorted(fn for fn in os.listdir(d) if fn.startswith('data-') and fn.endswith('.zip'))
        for fn in olds[:max(0, len(olds) - keep)]:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass
        return d
    except OSError as e:
        return '本地副本失败: %s' % e


def _name_now():
    """归档文件名。精确到分钟，避免同一分钟内触发两次互相覆盖。"""
    return 'data-%s.zip' % time.strftime('%Y%m%d-%H%M')


def run_once(name=None):
    """执行一次归档；返回 {'ok':bool,'name':str,'bytes':int,'detail':str}。"""
    cfg = _cfg()
    if not enabled():
        return {'ok': False, 'detail': '未配置归档目标（ZY_ARCHIVE_GITHUB_REPO/TOKEN 或 ZY_ARCHIVE_WEBHOOK）'}
    if not _run_lock.acquire(blocking=False):
        return {'ok': False, 'detail': '已有归档任务在执行'}
    try:
        name = name or _name_now()
        data = snapshot_bytes()
        notes = []
        if cfg['github_repo'] and cfg['github_token']:
            notes.append(push_github(cfg, name, data))
        if cfg['webhook']:
            notes.append(push_webhook(cfg, name, data))
        if cfg['local']:
            r = _save_local(name, data, cfg['keep'])
            notes.append('本地已保留（%s）' % r if not str(r).startswith('本地副本失败') else r)
        ok = not any(('失败' in n) for n in notes) and bool(notes)
        res = {'ok': ok, 'name': name, 'bytes': len(data), 'detail': '；'.join(notes),
               'ts': int(time.time())}
        with _lock:
            _last.update(res)
        print('[archive] %s %s' % ('OK' if ok else 'FAIL', res['detail']), flush=True)
        return res
    except Exception as e:  # noqa: BLE001
        with _lock:
            _last.update({'ok': False, 'detail': '归档异常: %s' % e, 'ts': int(time.time())})
        print('[archive] 异常: %r' % (e,), flush=True)
        return {'ok': False, 'detail': str(e)}
    finally:
        _run_lock.release()


def status():
    cfg = _cfg()
    with _lock:
        last = dict(_last)
    en = enabled()
    targets = [t for t in (
        ('github:' + cfg['github_repo']) if cfg['github_repo'] and cfg['github_token'] else '',
        'webhook' if cfg['webhook'] else '',
        'local' if cfg['local'] else '',
    ) if t]
    return {
        'enabled': en,
        'interval_hours': cfg['interval'],
        'keep': cfg['keep'],
        'targets': targets if en else [],   # 未启用时不显示"local"这种伪目标
        'last': last,
    }


def start_scheduler():
    """启动守护线程：启动 60 秒后跑第一次，之后每 interval 小时一次。

    免费容器平台会在无流量时休眠，进程被冻结/重启；醒来后立刻补跑一次，
    所以这里选「启动后很快跑一次」而不是「等满一个周期」。
    """
    global _started
    cfg = _cfg()
    if _started or not enabled() or cfg['interval'] <= 0:
        return False
    _started = True

    def loop():
        time.sleep(60)
        while True:
            try:
                run_once()
            except Exception as e:  # noqa: BLE001
                print('[archive] 调度异常: %r' % (e,), flush=True)
            time.sleep(max(300, int(cfg['interval'] * 3600)))

    t = threading.Thread(target=loop, name='zhiyuan-archive', daemon=True)
    t.start()
    print('[archive] 定时归档已启动：每 %g 小时一次，保留 %d 份'
          % (cfg['interval'], cfg['keep']), flush=True)
    return True
