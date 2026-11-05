# -*- coding: utf-8 -*-
"""大模型客户端：OpenAI 兼容接口（智谱GLM/DeepSeek/Qwen/本地Ollama均可），纯标准库实现。
未配置 API Key 时 available() 为 False，各模块自动降级为离线演示模式。"""
import json
import os
import re
import threading
import time
import urllib.request
import urllib.error

from . import store

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 配置文件位置：默认项目内 config.json；exe 打包后由启动器指向用户可写目录。
CONFIG_PATH = os.path.abspath(os.environ.get('ZY_CONFIG') or os.path.join(BASE, 'config.json'))

_DEFAULTS = {
    'llm': {
        'base_url': 'https://open.bigmodel.cn/api/paas/v4', 'api_key': '',
        'model': 'glm-4-flash', 'vision_model': 'glm-4v-flash', 'stream_url': '',
        # 免费兜底通道链：主通道报错（余额不足 402/400、限流 429、鉴权 401、网络失败）时按顺序自动重试。
        # 置为 [] 即可关闭。若某个端点需要 Key，在该项里写 "api_key" 字段。
        'fallback': [
            {'base_url': 'https://text.pollinations.ai/openai', 'model': 'openai-fast',
             'vision_model': ''},
        ],
    },
    'search': {'provider': '', 'api_key': ''}
}

# 请求级记录实际服务通道，便于前端/日志展示"本次回答由哪条通道生成"
_last = threading.local()

# 通道熔断表：base_url → 解除时间戳。失败的通道短期跳过，别让每次请求都先等死通道。
# 例：CloudBase 余额不足会秒回 400，但每次都先撞一次会拖慢整页响应。
_tripped = {}
_trip_lock = threading.Lock()
TRIP_SECONDS = 180

# ---------- 请求级用户上下文：LLM 配置按账号隔离 ----------
# 云端单实例多用户：系统默认（混元内置通道）为兜底，任何用户在设置弹窗保存的自定义
# Key 只写进自己的档案（PG 按账号隔离），只对自己的请求生效，互不可见不可用。
_user_ctx = threading.local()
USER_CFG_NAME = 'llm_config.json'


def set_request_user(sid):
    _user_ctx.sid = sid or None


def clear_request_user():
    _user_ctx.sid = None


def load_config(sid=None):
    """生效配置 = 系统默认（defaults → config.json → 环境变量）→ 当前用户覆盖（最高）。"""
    sid = sid or getattr(_user_ctx, 'sid', None)
    cfg = json.loads(json.dumps(_DEFAULTS))
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            user = json.load(f)
        for k, v in user.items():
            if k.startswith('_'):
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    except (OSError, ValueError):
        pass
    env_key = os.environ.get('LLM_API_KEY') or os.environ.get('BIGMODEL_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if env_key:
        cfg['llm']['api_key'] = env_key
    if os.environ.get('LLM_BASE_URL'):
        cfg['llm']['base_url'] = os.environ['LLM_BASE_URL']
    if os.environ.get('LLM_MODEL'):
        cfg['llm']['model'] = os.environ['LLM_MODEL']
    if sid:
        try:
            u = store._read_json(store._path(sid, USER_CFG_NAME), None) or {}
        except Exception:
            u = {}
        for sec in ('llm', 'search'):
            for k, v in (u.get(sec) or {}).items():
                # fallback 是列表：空数组有语义（=关闭兜底链），不能被 `if v` 过滤掉
                if v or (k == 'fallback' and isinstance(v, list)):
                    cfg[sec][k] = v
    return cfg


def save_user_config(sid, llm_fields=None, search_fields=None):
    """保存当前用户的自定义配置（只存显式提供的字段；系统默认不受影响）。

    约定：
      · 字符串：空值表示"不改"，非空则覆盖
      · 列表（如 fallback）：**空列表有语义**（=关闭兜底链），所以要能写入
    """
    if not sid:
        return False
    u = store._read_json(store._path(sid, USER_CFG_NAME), {}) or {}
    for sec, fields in (('llm', llm_fields or {}), ('search', search_fields or {})):
        for k, v in fields.items():
            if isinstance(v, list):
                u.setdefault(sec, {})[k] = v        # 列表按原样写（含 []）
            elif v:
                u.setdefault(sec, {})[k] = v
    store._write_json(store._path(sid, USER_CFG_NAME), u)
    return True


def save_config(cfg):
    """系统级配置（仅本机单档案默认场景使用；云端用户配置请走 save_user_config）。"""
    clean = {'llm': {k: v for k, v in cfg.get('llm', {}).items() if not k.startswith('_')},
             'search': {k: v for k, v in cfg.get('search', {}).items() if not k.startswith('_')}}
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)


def mask_key(key):
    if not key:
        return ''
    if len(key) <= 8:
        return key[:2] + '****'
    return key[:4] + '****' + key[-4:]


def vision_available():
    """是否有可用视觉能力：主通道有 vision_model，或兜底链里任意一条配了 vision_model。"""
    cfg = load_config()['llm']
    if cfg.get('api_key') and cfg.get('vision_model'):
        return True
    for fb in (cfg.get('fallback') or []):
        if not isinstance(fb, dict):
            continue
        if fb.get('vision_model') and (fb.get('api_key') or _keyless(dict(cfg, **fb))):
            return True
    return False


class LLMError(Exception):
    pass


def _host_private(host):
    """判断主机名是否属于本机/内网/链路本地等受保护地址。"""
    h = (host or '').strip().lower().rstrip('.')
    if h in ('localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]',
             'host.docker.internal', 'metadata.google.internal'):
        return True
    if h.endswith(('.local', '.internal', '.lan', '.home.arpa')):
        return True
    m = re.match(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$', h)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a in (0, 10, 127) or (a == 172 and 16 <= b <= 31) \
                or (a == 192 and b == 168) or (a == 169 and b == 254) \
                or (a == 100 and 64 <= b <= 127):
            return True
    if h.startswith('fd') or h.startswith('fe80'):   # IPv6 ULA / 链路本地
        return True
    return False


_dns_cache = {}          # host -> (expires_ts, ips)
_dns_lock = threading.Lock()


def _resolved_ips(host):
    """解析主机名并带 300s TTL 缓存（守卫每次请求都跑，避免 DNS 查询拖慢响应）。"""
    now = time.time()
    with _dns_lock:
        hit = _dns_cache.get(host)
        if hit and hit[0] > now:
            return hit[1]
    import socket
    ips = {info[4][0] for info in socket.getaddrinfo(host, None)}
    with _dns_lock:
        _dns_cache[host] = (now + 300, ips)
    return ips


def _guard_cloud_url(url):
    """云端多用户模式下的 SSRF 防护：禁止把 AI 请求指向内网/本机地址。
    本机单机模式不受影响（访问本地 Ollama 等属于正常用法）。
    含 DNS 解析后复检：公网域名若解析到内网 IP（DNS rebinding）同样拦截。"""
    try:
        from urllib.parse import urlparse
        from . import auth as _auth
        if not _auth.enabled():
            return
        host = urlparse(url).hostname or ''
        if _host_private(host):
            raise LLMError('安全限制：云端模式禁止将 AI 请求指向内网或本机地址')
        for ip in _resolved_ips(host):
            if _host_private(ip):
                raise LLMError('安全限制：目标域名解析到内网地址（%s），已拦截' % ip)
    except LLMError:
        raise
    except Exception:
        pass  # 判定失败时放行，避免误伤正常调用


def _keyless(cfg):
    """免 Key 公益端点（当前识别 pollinations.ai；其调用不发送 Authorization 头）。"""
    return 'pollinations.ai' in (cfg.get('base_url') or '')


def _is_gateway(cfg):
    """CloudBase 云函数网关端点：URL 即最终地址，不追加 /chat/completions。"""
    return 'tcloudbasegateway.com' in (cfg.get('base_url') or '')


def _endpoint(cfg):
    base = (cfg.get('base_url') or '').rstrip('/')
    return base if _is_gateway(cfg) or base.endswith('/chat/completions') else base + '/chat/completions'


# CloudBase 国内网关绕过系统代理直连（本地代理会间歇性丢包/挂起）
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open(req, timeout):
    """国内网关直连，其余走默认（含系统代理）。"""
    if 'tcloudbasegateway.com' in (req.full_url or ''):
        return _DIRECT.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _stream_url(cfg):
    """流式端点：优先配置 stream_url；OpenAI 兼容 SSE。无则返回 None（回退非流式）。"""
    s = (os.environ.get('LLM_STREAM_URL') or cfg.get('stream_url') or '').rstrip('/')
    if not s:
        return None
    return s if s.endswith('/chat/completions') else s + '/chat/completions'


def _usable(cfg):
    """该通道能否呼叫：有 Key，或是免 Key 端点。"""
    return bool(cfg.get('api_key')) or _keyless(cfg)


def available():
    """主通道或任一兜底通道可用即视为可用。

    否则「主通道没填 Key + 兜底是免 Key 公益通道」会被误判为不可用，
    整站直接掉进离线模式，兜底链等于白配。
    """
    cfg = load_config()['llm']
    if _usable(cfg):
        return True
    for fb in (cfg.get('fallback') or []):
        if isinstance(fb, dict) and fb.get('base_url'):
            if _usable(dict(cfg, **fb)):
                return True
    return False


def _channel_name(cfg):
    """给人看的通道名（日志 / 前端提示用）。"""
    base = cfg.get('base_url') or ''
    table = (
        ('pollinations.ai', 'Pollinations 免Key公益通道'),
        ('tcloudbasegateway.com', 'CloudBase 混元'),
        ('bigmodel.cn', '智谱 GLM'),
        ('siliconflow.cn', '硅基流动'),
        ('deepseek.com', 'DeepSeek'),
        ('dashscope.aliyuncs.com', '通义千问'),
        ('11434', '本地 Ollama'),
    )
    for frag, name in table:
        if frag in base:
            return name
    return base or '未配置'


def last_channel():
    """最近一次成功调用所用的通道名（线程级）。"""
    return getattr(_last, 'name', '')


def _record(channel, ok, ms, detail=''):
    """把一次模型调用记进指标（管理端用）。埋点失败绝不影响业务。"""
    try:
        from . import metrics
        metrics.record_llm(channel, ok, ms, sid=(getattr(_user_ctx, 'sid', None) or ''),
                           kind='chat', detail=detail)
    except Exception:  # noqa: BLE001
        pass


def _chain(fn, cfg, what='对话'):
    """按「主通道 → fallback 列表」顺序尝试调用。

    fn(channel_cfg) 抛 LLMError 时自动切下一条；全部失败则抛出汇总错误。
    兜底通道默认不继承主通道的 api_key，避免把主 Key 发往第三方端点。
    失败的通道会被熔断一段时间（默认 180s），避免每次请求都先等一遍死通道。
    """
    channels = [cfg]
    for fb in (cfg.get('fallback') or []):
        if not isinstance(fb, dict) or not fb.get('base_url'):
            continue
        c = dict(cfg)
        c.pop('fallback', None)
        c['api_key'] = ''          # 默认不继承主 Key
        c['stream_url'] = ''       # 兜底通道走非流式，避免端点路径不匹配
        c.update(fb)
        channels.append(c)

    now = time.time()
    alive = [c for c in channels
             if c.get('api_key') or _keyless(c)]
    # 全部被熔断时强制全试一遍（避免全死锁）
    usable = [c for c in alive if _tripped.get(c.get('base_url'), 0) < now] or alive
    if not usable:
        raise LLMError('未配置大模型 API Key（可在「⚙ 接入设置」选择免Key通道或填入 api_key）')

    errors = []
    for c in usable:
        t0 = time.time()
        name = _channel_name(c)
        try:
            out = fn(c)
        except LLMError as e:
            errors.append('%s → %s' % (name, e))
            _record(name, False, (time.time() - t0) * 1000, str(e))
            with _trip_lock:
                _tripped[c.get('base_url')] = time.time() + TRIP_SECONDS
            continue
        with _trip_lock:
            _tripped.pop(c.get('base_url'), None)   # 恢复：清熔断
        _record(name, True, (time.time() - t0) * 1000)
        _last.name = name
        return out

    if len(errors) == 1:
        raise LLMError(errors[0])
    raise LLMError('%s全部通道均失败：%s' % (what, '；'.join(errors)))


def channel_status():
    """各通道当前状态（前端/诊断用）：[{name, base_url, tripped_for}]"""
    now = time.time()
    cfg = load_config()['llm']
    chans = [cfg] + [dict(cfg, **fb) for fb in (cfg.get('fallback') or [])
                     if isinstance(fb, dict) and fb.get('base_url')]
    out = []
    for i, c in enumerate(chans):
        out.append({
            'name': _channel_name(c),
            'role': '主通道' if i == 0 else '兜底',
            'model': c.get('model', ''),
            'tripped_for': max(0, int(_tripped.get(c.get('base_url'), 0) - now)),
        })
    return out


def _chat_once(cfg, messages, temperature=0.6, timeout=120, max_tokens=4000):
    """单次调用（不含兜底）。"""
    if not cfg.get('api_key') and not _keyless(cfg):
        raise LLMError('未配置大模型 API Key（可在「⚙ 接入设置」选择免Key通道或填入 api_key）')
    url = _endpoint(cfg)
    _guard_cloud_url(url)
    body = json.dumps({
        'model': cfg.get('model', 'glm-4-flash'),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if cfg.get('api_key'):
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    req = urllib.request.Request(url, data=body, method='POST', headers=headers)
    try:
        with _open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        raise LLMError('LLM HTTP %s: %s' % (e.code, detail))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError('LLM 请求失败: %s' % e)
    if isinstance(data, dict) and data.get('error'):
        msg = data['error'].get('message') if isinstance(data['error'], dict) else str(data['error'])
        raise LLMError('LLM 错误: %s' % msg)
    try:
        return data['choices'][0]['message']['content']
    except (KeyError, IndexError) as e:
        raise LLMError('LLM 返回格式异常: %s' % e)


def chat(messages, temperature=0.6, timeout=120, max_tokens=4000):
    cfg = load_config()['llm']
    return _chain(lambda c: _chat_once(c, messages, temperature, timeout, max_tokens), cfg)


def _extract_json(text):
    """从模型输出中提取第一个完整的 JSON 对象（容忍 ```json 围栏、前后说明文字）。

    小模型/推理模型常因 max_tokens 截断而吐出"缺尾巴"的 JSON（推理 token 也占额度），
    因此最后会尝试补全括号、并在最近的逗号处裁掉残缺字段后再解析。
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith('```'):
        text = text.strip('`').lstrip('json').strip()
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                seg = text[start:i + 1]
                # 先修转义再解析：`$3\times3$` 这种在语法上是"合法 JSON"（\t 被当成制表符），
                # 不修就会把数学式子悄悄改坏；修转义对合法 JSON 是幂等的。
                try:
                    return json.loads(_fix_escapes(seg))
                except ValueError:
                    try:
                        return json.loads(seg)
                    except ValueError:
                        return _repair_json(seg)
    return _repair_json(text[start:])


def _close_brackets(frag):
    """给被截断的 JSON 片段补齐未闭合的字符串与括号。"""
    out = []
    stack = []
    in_str = False
    esc = False
    for c in frag:
        out.append(c)
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            stack.append('}')
        elif c == '[':
            stack.append(']')
        elif c in '}]':
            if stack:
                stack.pop()
    if in_str:
        out.append('"')
    while stack:
        out.append(stack.pop())
    return ''.join(out)


def _fix_escapes(frag):
    r"""修复模型输出里非法的 JSON 转义（最常见的元凶：LaTeX 反斜杠）。

    `{"explanation":"$$\\det A$$"}` 这种是合法的，但模型常直接写成 `"$$\det A$$"`，
    json.loads 会报 `Invalid \escape`。这里把字符串内所有非法转义改成字面反斜杠。
    对合法 JSON 是幂等的（`\\\\`、`\\n` 等都会原样保留）。
    """
    out = []
    i, n = 0, len(frag)
    in_str = False
    ctrl = {'\n': '\\n', '\r': '\\r', '\t': '\\t', '\b': '\\b', '\f': '\\f'}
    while i < n:
        c = frag[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            i += 1
            continue
        if c == '"':
            out.append(c)
            in_str = False
            i += 1
            continue
        if c == '\\':
            nxt = frag[i + 1] if i + 1 < n else ''
            if nxt in '"\\/':
                out.append(frag[i:i + 2])
                i += 2
                continue
            if nxt in 'bfnrt':
                # 歧义区：合法转义 \\b \\f \\n \\r \\t 与 LaTeX 命令 \\begin \\frac \\nabla \\right \\times 撞车。
                # 后面紧跟英文字母时按 LaTeX 处理（\\times、\\begin 这种高频得多）；
                # 否则（后面是空格/标点/中文/$）保留原本的换行、制表等转义语义。
                after = frag[i + 2] if i + 2 < n else ''
                if after.isascii() and after.isalpha():
                    out.append('\\\\')
                    i += 1
                    continue
                out.append(frag[i:i + 2])
                i += 2
                continue
            if nxt == 'u':
                hexs = frag[i + 2:i + 6]
                if len(hexs) == 4 and all(h in '0123456789abcdefABCDEF' for h in hexs):
                    out.append(frag[i:i + 6])
                    i += 6
                    continue
            out.append('\\\\')      # 非法转义 → 退化成字面反斜杠
            i += 1
            continue
        if c in ctrl:
            out.append(ctrl[c])
            i += 1
            continue
        if ord(c) < 0x20:
            out.append('\\u%04x' % ord(c))
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _repair_json(frag):
    """把被截断/带非法转义的 JSON 尽量救回：先修转义，再逐个裁掉尾部残缺字段。"""
    cand = _fix_escapes(frag)
    for _ in range(8):
        try:
            v = json.loads(_close_brackets(cand))
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
        cut = max(cand.rfind(','), cand.rfind(':') if cand.rfind(':') > 0 else -1)
        if cut <= 0:
            return None
        cand = cand[:cut]
    return None


def _vision_once(cfg, prompt, image_bytes, mime, temperature, timeout):
    """单次视觉调用（不含兜底）。"""
    import base64
    model = cfg.get('vision_model') or cfg.get('model')
    if not model:
        raise LLMError('该通道未配置视觉模型')
    url = _endpoint(cfg)
    b64 = base64.b64encode(image_bytes).decode()
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (mime, b64)}},
            {'type': 'text', 'text': prompt},
        ]}],
        'temperature': temperature,
        'max_tokens': 3000,
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if cfg.get('api_key'):
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    req = urllib.request.Request(url, data=body, method='POST', headers=headers)
    try:
        with _open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        raise LLMError('视觉模型 HTTP %s: %s' % (e.code, e.read().decode('utf-8', 'replace')[:200]))
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError) as e:
        raise LLMError('视觉模型请求失败: %s' % e)


def chat_vision(prompt, image_bytes, mime='image/png', temperature=0.4, timeout=180):
    """视觉模型识别图片（题图/手写作文）。

    「视觉兜底」：主通道没配 vision_model 或调用失败时，按顺序尝试兜底链里
    **配了 vision_model 的通道**。这样主通道是纯文本模型（如 glm-4-flash）时，
    仍可把免费视觉模型（如 glm-4v-flash）挂到兜底链上专门读图。
    """
    cfg = load_config()['llm']

    candidates = []
    if cfg.get('vision_model'):
        candidates.append(cfg)
    for fb in (cfg.get('fallback') or []):
        if not isinstance(fb, dict) or not fb.get('base_url'):
            continue
        if not fb.get('vision_model'):
            continue                       # 没有视觉模型的兜底通道直接跳过
        c = dict(cfg)
        c.pop('fallback', None)
        c['api_key'] = ''                  # 不把主 Key 发给第三方（除非该条自带）
        c['stream_url'] = ''
        c.update(fb)
        candidates.append(c)

    if not candidates:
        raise LLMError('未配置视觉模型：请在主通道或兜底链里填 vision_model '
                       '（推荐免费的 glm-4v-flash）')

    errors = []
    for c in candidates:
        if not c.get('api_key') and not _keyless(c):
            continue
        t0 = time.time()
        name = _channel_name(c)
        try:
            out = _vision_once(c, prompt, image_bytes, mime, temperature, timeout)
        except LLMError as e:
            errors.append('%s → %s' % (name, e))
            _record(name, False, (time.time() - t0) * 1000, 'vision')
            continue
        _record(name, True, (time.time() - t0) * 1000, 'vision')
        _last.name = name
        return out

    if not errors:
        raise LLMError('视觉通道都缺少 API Key')
    raise LLMError('视觉模型全部通道均失败：%s' % '；'.join(errors))


def chat_stream(messages, on_delta=None, temperature=0.6, timeout=120, max_tokens=4000):
    """流式对话：OpenAI 兼容 SSE，on_delta(chunk) 逐段回调；失败自动回退非流式。返回完整文本。"""
    cfg = load_config()['llm']
    url = _stream_url(cfg)
    if url:
        _guard_cloud_url(url)
    if not url or (not cfg.get('api_key') and not _keyless(cfg)):
        out = chat(messages, temperature=temperature, timeout=timeout, max_tokens=max_tokens)
        if on_delta:
            on_delta(out)
        return out
    body = json.dumps({
        'model': cfg.get('model', 'glm-4-flash'),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': True,
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    if cfg.get('api_key'):
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    req = urllib.request.Request(url, data=body, method='POST', headers=headers)
    chunks = []
    try:
        with _open(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    j = json.loads(payload)
                except ValueError:
                    continue
                ch = (j.get('choices') or [{}])[0]
                delta = ((ch.get('delta') or {}).get('content')) or ch.get('text') or ''
                if j.get('error'):
                    raise LLMError(str(j['error'])[:200])
                if delta:
                    chunks.append(delta)
                    if on_delta:
                        on_delta(delta)
    except LLMError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        out = chat(messages, temperature=temperature, timeout=timeout, max_tokens=max_tokens)
        if on_delta:
            on_delta(out)
        return out
    full = ''.join(chunks).strip()
    if not full:
        out = chat(messages, temperature=temperature, timeout=timeout, max_tokens=max_tokens)
        if on_delta:
            on_delta(out)
        return out
    return full


def chat_json(messages, temperature=0.3, timeout=180, max_tokens=6000, retries=1):
    """要求模型输出 JSON 并解析；失败时重试一次。返回 dict 或 None。

    max_tokens 调高到 6000：推理型模型（如免费通道的 gpt-oss）会把推理 token 也算进额度，
    留 4000 容易把 JSON 截断（表现为"JSON 解析失败"），再叠加 _extract_json 的截断修复。
    """
    msgs = list(messages) + [{'role': 'system',
                              'content': '只输出一个合法的 JSON 对象，不要输出任何解释文字或代码围栏。'}]
    last = None
    for i in range(retries + 1):
        try:
            out = chat(msgs, temperature=temperature, timeout=timeout, max_tokens=max_tokens)
        except LLMError as e:
            last = e
            continue
        parsed = _extract_json(out)
        if isinstance(parsed, dict):
            return parsed
        last = LLMError('JSON 解析失败: %r' % out[:200])
    if last:
        raise last
    return None
