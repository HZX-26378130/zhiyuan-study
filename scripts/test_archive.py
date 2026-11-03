# -*- coding: utf-8 -*-
"""归档功能回归测试（纯离线，用本地桩服务器模拟 GitHub Contents API）。

用法：py -3 scripts/test_archive.py
覆盖：
  1. 快照内容正确（含 data/db，排除 config.json 与 archive 自身）
  2. 推送到 GitHub：首次 PUT、已存在时带 sha 覆盖
  3. 保留份数裁剪（keep=2 时远端只留 2 个）
  4. 鉴权失败时不抛异常、返回 ok=False
  5. webhook 目标能收到 zip
"""
import base64
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _console import utf8
    utf8()
except Exception:  # noqa: BLE001
    pass

from backend import archive, store  # noqa: E402

FAKE_REPO = 'tester/zhiyuan-backup'
FILES = {}          # name -> {sha, content}
WEBHOOK_GOT = []
FORBID = {'v': False}


def _ssh(name):
    """稳定假 sha"""
    import hashlib
    return hashlib.sha1(name.encode()).hexdigest()


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    def _parts(self):
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split('/') if p]
        # /repos/<owner>/<repo>/contents/<path...>
        assert parts[0] == 'repos' and parts[3] == 'contents', path
        return parts[4:]

    def do_GET(self):
        if self.path.startswith('/hook'):
            self._json(200, {'ok': True})
            return
        if FORBID['v']:
            self._json(401, {'message': 'Bad credentials'})
            return
        try:
            rest = self._parts()
        except AssertionError:
            self._json(404, {'message': 'not found'})
            return
        if not rest or rest[-1] == 'backups':   # 列目录（真实 GitHub 对目录返回数组）
            items = [{'name': n, 'sha': v['sha'], 'type': 'file'}
                     for n, v in sorted(FILES.items())]
            self._json(200, items)
        else:
            name = rest[-1]
            if name in FILES:
                self._json(200, {'name': name, 'sha': FILES[name]['sha']})
            else:
                self._json(404, {'message': 'Not Found'})

    def do_PUT(self):
        if FORBID['v']:
            self._json(401, {'message': 'Bad credentials'})
            return
        name = self._parts()[-1]
        payload = json.loads(self._read() or b'{}')
        content = base64.b64decode(payload.get('content') or '')
        if name in FILES and payload.get('sha') != FILES[name]['sha']:
            self._json(409, {'message': 'sha mismatch'})
            return
        FILES[name] = {'sha': _ssh(name + str(len(content))), 'content': content}
        self._json(201 if name not in FILES else 200, {'content': {'name': name}})

    def do_DELETE(self):
        name = self._parts()[-1]
        if name in FILES:
            del FILES[name]
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
        else:
            self._json(404, {'message': 'Not Found'})

    def do_POST(self):
        body = self._read()
        if self.path.startswith('/hook'):
            WEBHOOK_GOT.append((self.headers.get('X-Archive-Name'), body))
            self._json(200, {'ok': True})
            return
        self._json(404, {'message': 'not found'})


def main():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d' % port

    os.environ['ZY_ARCHIVE_GITHUB_API'] = base
    os.environ['ZY_ARCHIVE_GITHUB_REPO'] = FAKE_REPO
    os.environ['ZY_ARCHIVE_GITHUB_TOKEN'] = 'fake-token'
    os.environ['ZY_ARCHIVE_GITHUB_BRANCH'] = 'main'
    os.environ['ZY_ARCHIVE_GITHUB_DIR'] = 'backups'
    os.environ['ZY_ARCHIVE_KEEP'] = '2'
    os.environ['ZY_ARCHIVE_LOCAL'] = '0'
    os.environ.pop('ZY_ARCHIVE_WEBHOOK', None)

    fails = []

    def check(cond, msg):
        print('[%s] %s' % ('OK' if cond else 'FAIL', msg))
        if not cond:
            fails.append(msg)

    # ---------- 1. 快照 ----------
    data = archive.snapshot_bytes()
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    check(len(data) > 1000, '快照非空（%d 字节）' % len(data))
    check(any('/profile.json' in n or 'students.json' in n for n in names), '快照含学生数据')
    check(not any(n.endswith('/config.json') or n.endswith('/llm_config.json') for n in names),
          '快照不含 config.json / llm_config.json（防 Key 外泄）')
    check(not any('/archive/' in n for n in names), '快照不含 archive 自身（防递归）')

    # ---------- 2 & 3. 推送 + 裁剪 ----------
    # 每次用不同文件名，模拟跨天归档（真实环境按分钟命名，同一分钟会覆盖）
    for i in range(5):
        r = archive.run_once(name='data-2026110%d-0300.zip' % (i + 1))
        check(r.get('ok') is True, '第 %d 次推送成功（%s）' % (i + 1, r.get('detail', '')[:60]))
    check(len(FILES) == 2, 'keep=2 生效：远端剩 %d 个（期望 2）' % len(FILES))

    # 同名重复推送 → 走带 sha 的覆盖分支
    before = dict(FILES)
    r = archive.run_once(name='data-20261105-0300.zip')
    check(r.get('ok') is True and FILES.keys() == before.keys(),
          '同名覆盖成功（带 sha，文件数不变）')

    # ---------- 4. 鉴权失败 ----------
    FORBID['v'] = True
    r = archive.run_once()
    check(r.get('ok') is False and '失败' in r.get('detail', ''), '鉴权失败时 ok=False 且不抛异常')
    FORBID['v'] = False

    # ---------- 5. webhook ----------
    os.environ['ZY_ARCHIVE_WEBHOOK'] = base + '/hook'
    r = archive.run_once()
    check(r.get('ok') is True and WEBHOOK_GOT, 'webhook 收到 zip（%d 字节）'
          % (len(WEBHOOK_GOT[-1][1]) if WEBHOOK_GOT else 0))
    check(WEBHOOK_GOT and WEBHOOK_GOT[-1][0].startswith('data-'), 'webhook 带 X-Archive-Name 头')

    # ---------- 6. status ----------
    st = archive.status()
    check(st['enabled'] and 'github:' + FAKE_REPO in st['targets'], 'status 报告目标正确')

    srv.shutdown()
    print('\n%d/%d 通过' % (9 - len(fails), 9) if fails else '\n全部通过 ✓')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
