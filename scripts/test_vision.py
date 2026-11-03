# -*- coding: utf-8 -*-
"""视觉兜底回归测试（纯离线，本地桩服务模拟 OpenAI 兼容视觉接口）。

用法：py -3 scripts/test_vision.py
覆盖：
  1. 主通道没有 vision_model 时，自动改用兜底链里配了 vision_model 的通道
  2. 主通道有视觉但调用失败（401）→ 自动降级到兜底视觉通道
  3. 兜底链里的通道默认不继承主通道 api_key
  4. 全部不可用时给出可读的错误信息
  5. vision_available() 能识别"视觉能力在兜底链里"的情况
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _console import utf8
    utf8()
except Exception:  # noqa: BLE001
    pass

_tmp = tempfile.mkdtemp(prefix='zy_vis_')
os.environ['ZY_DATA_DIR'] = os.path.join(_tmp, 'data')
os.environ['ZY_CONFIG'] = os.path.join(_tmp, 'config.json')
os.environ.pop('ZY_AUTH', None)

from backend import llm  # noqa: E402

CALLS = []          # 记录每次调用看到的 model 与 Authorization


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(n) or b'{}')
        model = body.get('model')
        auth = self.headers.get('Authorization') or ''
        CALLS.append({'model': model, 'auth': auth, 'path': self.path})
        if model == 'bad-vision':
            self.send_response(401)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        out = json.dumps({'choices': [{'message': {'content': 'OCR结果：f(x)=x^2'}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def write_cfg(cfg):
    os.makedirs(os.path.dirname(os.environ['ZY_CONFIG']), exist_ok=True)
    with open(os.environ['ZY_CONFIG'], 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False)


def main():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = 'http://127.0.0.1:%d/v1' % port

    fails = []

    def check(cond, msg):
        print('[%s] %s' % ('OK' if cond else 'FAIL', msg))
        if not cond:
            fails.append(msg)

    # ---------- 1. 主通道无视觉 → 用兜底视觉通道 ----------
    CALLS.clear()
    write_cfg({'llm': {
        'base_url': base, 'api_key': 'primary-key', 'model': 'text-only',
        'vision_model': '',                      # ← 主通道没有视觉
        'fallback': [{'base_url': base, 'model': 'text-only',
                      'vision_model': 'good-vision', 'api_key': 'fallback-key'}],
    }})
    txt = llm.chat_vision('读一下这道题', b'\x89PNG fake', 'image/png', timeout=10)
    check(txt.startswith('OCR结果'), '主通道无视觉时改用兜底视觉通道，返回: %r' % txt[:20])
    check(len(CALLS) == 1 and CALLS[0]['model'] == 'good-vision',
          '实际调用的模型是兜底通道的 good-vision（实际 %s）' % [c['model'] for c in CALLS])
    check(CALLS[0]['auth'] == 'Bearer fallback-key',
          '使用了兜底通道自己的 Key（不继承主通道）')

    # ---------- 2. 主通道视觉失败 → 降级 ----------
    CALLS.clear()
    write_cfg({'llm': {
        'base_url': base, 'api_key': 'primary-key', 'model': 'text-only',
        'vision_model': 'bad-vision',            # ← 会返回 401
        'fallback': [{'base_url': base, 'model': 'text-only',
                      'vision_model': 'good-vision', 'api_key': 'fallback-key'}],
    }})
    txt = llm.chat_vision('读图', b'\x89PNG fake', 'image/png', timeout=10)
    check(txt.startswith('OCR结果'), '主通道视觉 401 后自动降级到兜底')
    check([c['model'] for c in CALLS] == ['bad-vision', 'good-vision'],
          '调用顺序符合预期：%s' % [c['model'] for c in CALLS])

    # ---------- 3. 兜底通道不带 Key 且非免 Key 端点 → 跳过（不会把主 Key 发出去） ----------
    CALLS.clear()
    write_cfg({'llm': {
        'base_url': base, 'api_key': 'primary-key', 'model': 'text-only',
        'vision_model': 'bad-vision',
        'fallback': [{'base_url': base, 'model': 'text-only', 'vision_model': 'good-vision'}],
    }})
    try:
        llm.chat_vision('读图', b'\x89PNG', 'image/png', timeout=10)
        check(False, '缺 Key 的兜底视觉通道不应被调用')
    except llm.LLMError:
        check(True, '缺 Key 的兜底视觉通道被跳过（不会外泄主 Key）')
    check(all(c['auth'] != 'Bearer primary-key' or c['model'] == 'bad-vision' for c in CALLS),
          '主 Key 只发给了主通道')

    # ---------- 4. 完全没有视觉能力 → 可读错误 ----------
    write_cfg({'llm': {'base_url': base, 'api_key': 'k', 'model': 'text-only',
                       'vision_model': '', 'fallback': []}})
    try:
        llm.chat_vision('读图', b'\x89PNG', 'image/png', timeout=5)
        check(False, '无视觉能力时应报错')
    except llm.LLMError as e:
        check('vision_model' in str(e), '无视觉能力时提示要配 vision_model：%s' % str(e)[:40])
    check(llm.vision_available() is False, 'vision_available() 正确返回 False')

    # ---------- 5. 视觉能力在兜底链里 → available 为 True ----------
    write_cfg({'llm': {
        'base_url': base, 'api_key': 'primary-key', 'model': 'text-only', 'vision_model': '',
        'fallback': [{'base_url': base, 'model': 'text-only',
                      'vision_model': 'good-vision', 'api_key': 'fallback-key'}],
    }})
    check(llm.vision_available() is True, 'vision_available() 识别到兜底链里的视觉能力')

    srv.shutdown()
    print()
    if fails:
        print('%d 项失败' % len(fails))
        return 1
    print('全部通过 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
