# -*- coding: utf-8 -*-
"""知源学伴 · AI辅助学习系统 启动入口
用法：py -3 server.py [端口]   （默认 8765）
浏览器访问：http://127.0.0.1:8765
"""
import os
import socket
import sys
from http.server import ThreadingHTTPServer

# Windows 默认控制台编码可能是 GBK（cp936）：直接打印 ✓ / 中文会抛 UnicodeEncodeError 导致服务起不来。
# 统一把标准输出改为 UTF-8 且编码失败不致命（启动横幅、日志不该让进程崩溃）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import archive, llm  # noqa: E402
from backend.http_app import Handler  # noqa: E402

BANNER = r"""
==========================================================
   知源学伴  ·  AI 辅助学习系统  (ZhiYuan Study Companion)
----------------------------------------------------------
   AI知识问答(线代/数分) | 英语批改(作文/翻译)
   四六级词汇检测 | 薄弱点画像 | 诊断卷 | 讲义
   校本资料库 | 自我迭代记忆（反馈→反思→策略更新）
==========================================================
"""


def _pick_port():
    """端口优先级：命令行参数 → 环境变量 PORT → 8765。

    注意 sys.argv[1] 不能直接下标：不带参数启动（systemd、双击）会 IndexError 崩溃。
    """
    if len(sys.argv) > 1 and sys.argv[1].strip():
        arg = sys.argv[1].strip()
        if arg.isdigit():
            return int(arg)
        print('  ! 端口参数 %r 不是数字，改用默认值' % arg)
    env = (os.environ.get('PORT') or '').strip()
    if env.isdigit():
        return int(env)
    return 8765


class DualStackServer(ThreadingHTTPServer):
    """同时监听 IPv6 与 IPv4（同一端口）。

    为什么需要：不少校园网（如 CERNET2）给每台机器一个公网 IPv6 地址，
    同学们可以直接用 http://[2001:da8::xxxx]:8765 访问 —— 不需要任何隧道、
    没有任何流量配额。而 Python 默认只绑 IPv4，白白浪费这条通路。

    IPV6_V6ONLY=0 打开后，同一 socket 也接受 IPv4 连接（映射为 ::ffff:1.2.3.4），
    所以双栈一个监听就够。
    """
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def _is_ipv6_host(host):
    return ':' in host or host in ('::', '::1')


def _make_server(host, port):
    if _is_ipv6_host(host):
        return DualStackServer((host, port), Handler)
    return ThreadingHTTPServer((host, port), Handler)


def _lan_ipv4():
    """猜一个局域网 IPv4（UDP connect 不实际发包）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(('223.5.5.5', 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ''


def _public_ipv6s():
    """本机全局 IPv6 地址（2xxx/3xxx 开头才是公网可路由）。"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
            ip = info[4][0].split('%')[0]
            if ip.startswith(('2', '3')) and ip not in out:
                out.append(ip)
    except (socket.gaierror, OSError):
        pass
    return out


def main():
    port = _pick_port()
    host = os.environ.get('ZY_HOST', '127.0.0.1')
    server = _make_server(host, port)
    print(BANNER)
    print('  大模型: %s' % ('已配置 ✓  (%s)' % llm.load_config()['llm']['model'] if llm.available()
                           else '未配置 → 离线演示模式（内置知识库/启发式批改可用）'))
    print('  词库:   CET-4 + CET-6（GitHub开源词库已内置）')
    st = archive.status()
    if st['enabled']:
        print('  归档:   每 %g 小时 → %s（保留 %d 份）'
              % (st['interval_hours'], '、'.join(st['targets']), st['keep']))
    else:
        print('  归档:   未启用（免费容器平台建议启用，见 deploy/archive/README.md）')

    print('  监听:   %s:%d' % (host, port))
    if host in ('0.0.0.0', '::'):
        print('  本机:   http://127.0.0.1:%d' % port)
        lan = _lan_ipv4()
        if lan:
            print('  局域网: http://%s:%d   （同一 WiFi 的同学可用这个）' % (lan, port))
        v6s = _public_ipv6s()
        for ip in v6s[:2]:
            print('  公网V6: http://[%s]:%d   （校园网 IPv6 可直连，无需隧道/无配额）' % (ip, port))
        if not v6s:
            print('  （未检测到公网 IPv6：校园网可能未开启双栈，隧道仍是更稳的选择）')
        print('  ⚠ 暴露到公网请确保已设 ZY_AUTH=1（否则谁都能看数据）')
    else:
        print('  地址:   http://%s:%d   （Ctrl+C 退出）' % ('127.0.0.1' if host == '127.0.0.1' else host, port))
    print()
    archive.start_scheduler()      # 免费容器平台没有 cron，定时器跑在进程内
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n再见！')


if __name__ == '__main__':
    main()
