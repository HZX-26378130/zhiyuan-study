# -*- coding: utf-8 -*-
"""知源学伴 · 桌面版启动器（PyInstaller 入口）

职责：
1. 把「数据目录」与「程序资源目录」分开 —— 这是 exe 化的关键
   · 资源（frontend/、词库、知识图谱、真题库）来自打包内的只读目录
   · 数据（档案/错题/积分/图片/指标）写到用户可写目录：
       优先 ZY_DATA_DIR → 否则 %APPDATA%\知源学伴  （macOS/Linux 用 ~/.zhiyuan-study）
2. 首次启动自动生成 config.json（智谱 GLM 预设 + 免 Key 兜底通道）
3. 起服务后自动打开浏览器，控制台保留端口与数据目录提示
4. 端口被占用时自动往后找可用端口

打包时以本文件为入口；直接 `python packaging/run_exe.py` 也能跑（用于构建前自测）。
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

APP_NAME = '知源学伴'


def _resource_dir():
    """只读资源目录：PyInstaller 解压目录 或 项目根。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir(res):
    """可写数据目录（跨平台）。"""
    env = (os.environ.get('ZY_DATA_DIR') or '').strip()
    if env:
        return os.path.abspath(env)
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, APP_NAME)


def _ensure_config(target_cfg, res):
    """首次启动写一份默认可用的 config.json（不覆盖已有配置）。"""
    if os.path.exists(target_cfg):
        return False
    import json
    default = {
        'llm': {
            'base_url': 'https://open.bigmodel.cn/api/paas/v4',
            'api_key': '',
            'model': 'glm-4-flash',
            'vision_model': 'glm-4v-flash',
            'stream_url': '',
            'fallback': [
                {'base_url': 'https://text.pollinations.ai/openai',
                 'model': 'openai-fast', 'vision_model': ''},
            ],
        },
        'search': {'provider': '', 'api_key': ''},
    }
    os.makedirs(os.path.dirname(target_cfg), exist_ok=True)
    with open(target_cfg, 'w', encoding='utf-8') as f:
        json.dump(default, f, ensure_ascii=False, indent=2)
    return True


def _free_port(start=8765, tries=30):
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', p))
                return p
            except OSError:
                continue
    return start


def _seed_assets(data_dir, res):
    """把只读资源里的静态数据（词库/图谱/题库/评分标准）同步到数据目录。

    约定：ZY_DATA_DIR 就是项目里 `data/` 的等价物（内部会用到 <ZY_DATA_DIR>/knowledge、
    <ZY_DATA_DIR>/db 等），所以直接复制到 data_dir/<sub>，不要多套一层。

    升级行为：不能只在"目录不存在"时复制 —— 否则新版 exe 里更新的词库/知识图谱
    永远到不了老用户手里。这里按文件逐个比对（缺失或大小不同就覆盖）；
    用户自己的学习数据都在 db/ 下，不受影响。
    """
    import shutil
    src_data = os.path.join(res, 'data')
    if not os.path.isdir(src_data):
        return

    def sync(src, dst):
        try:
            os.makedirs(dst, exist_ok=True)
        except OSError:
            return
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target = dst if rel == '.' else os.path.join(dst, rel)
            try:
                os.makedirs(target, exist_ok=True)
            except OSError:
                continue
            for fn in files:
                s = os.path.join(root, fn)
                d = os.path.join(target, fn)
                try:
                    if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
                        continue        # 大小一致视为同一份（这些都是小 JSON，够用）
                    shutil.copy2(s, d)
                except OSError:
                    continue

    for sub in ('vocab', 'knowledge', 'bank', 'rubrics'):
        s = os.path.join(src_data, sub)
        if os.path.isdir(s):
            sync(s, os.path.join(data_dir, sub))


def main():
    res = _resource_dir()
    data = _data_dir(res)
    os.makedirs(data, exist_ok=True)
    _seed_assets(data, res)

    cfg = os.path.join(data, 'config.json')
    created = _ensure_config(cfg, res)

    # 关键：让后端所有模块按这两个环境变量找资源与写数据
    os.environ.setdefault('ZY_DATA_DIR', data)
    os.environ.setdefault('ZY_CONFIG', cfg)
    os.environ.setdefault('ZY_FRONTEND', os.path.join(res, 'frontend'))
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # 桌面版是单机应用：默认免登录；管理端因此默认对本机开放
    os.environ.pop('ZY_AUTH', None)

    sys.path.insert(0, res)
    from backend import archive, llm                       # noqa: E402
    from backend.http_app import Handler                   # noqa: E402

    port = _free_port(int(os.environ.get('PORT') or 8765))
    host = '127.0.0.1'
    server = ThreadingHTTPServer((host, port), Handler)
    url = 'http://%s:%d' % (host, port)

    print('=' * 58)
    print('  %s · 桌面版' % APP_NAME)
    print('-' * 58)
    print('  数据目录: %s' % data)
    print('  配置文件: %s%s' % (cfg, '（已生成默认配置）' if created else ''))
    print('  大模型  : %s' % ('已配置 ✓ (%s)' % llm.load_config()['llm']['model']
                              if llm.available() else '未配置 → 离线知识库模式'))
    st = archive.status()
    print('  归档    : %s' % ('每 %g 小时' % st['interval_hours'] if st['enabled'] else '未启用'))
    print('  管理端  : %s/  → 侧栏「🛠 管理端」' % url)
    print('  地址    : %s   （关闭本窗口即退出）' % url)
    print('=' * 58)
    print()

    def _open():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_open, daemon=True).start()
    try:
        archive.start_scheduler()
    except Exception:  # noqa: BLE001
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已退出。数据仍在：%s' % data)


if __name__ == '__main__':
    main()
