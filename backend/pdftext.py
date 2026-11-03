# -*- coding: utf-8 -*-
"""PDF 文本提取（纯标准库，不依赖 pypdf / pdfminer）。

为什么自己写：项目的卖点是「零第三方依赖」，为读 PDF 引入一个大依赖不划算。

支持范围（诚实的边界）：
    ✅ 带文本层的 PDF（绝大多数课件、讲义、论文）
    ✅ FlateDecode 压缩的内容流与字体 CMap
    ✅ 通过 ToUnicode CMap 还原中文（CID 字体最常见的做法）
    ✅ 未压缩/压缩混排、多页（按页分隔）
    ❌ 扫描件/纯图片 PDF（没有文本层，需要 OCR）
    ❌ 加密 PDF（/Encrypt，直接给出明确提示）
    ❌ 复杂的多字体子集混排：中文可能有少量错字（尽力而为）

实现思路：
    1. 扫描所有 `stream…endstream`，能解压就解压
    2. 含 beginbfchar/beginbfrange 的流 → 解析成「字符码 → Unicode」映射表
    3. 含 BT…ET 的流 → 按 Tj/TJ/'/" 提取字符串，套映射表还原文字
    4. 按 Tm/Td/T*/ET 等操作符补换行，最后清理空白
"""
import re
import zlib

MAX_STREAM = 8 * 1024 * 1024      # 单个流上限，防止畸形文件撑爆内存
MAX_OUTPUT = 400 * 1024           # 提取结果上限


# ---------------- 基础工具 ----------------

def _find_streams(raw):
    """产出 (流的字典头串, 流字节)。"""
    for m in re.finditer(rb'stream\r?\n', raw):
        start = m.end()
        end = raw.find(b'endstream', start)
        if end < 0:
            continue
        body = raw[start:end]
        if len(body) > MAX_STREAM:
            continue
        # 往前找最近的 << 作为字典头（粗略但够用）
        head_start = raw.rfind(b'<<', max(0, m.start() - 2000), m.start())
        head = raw[head_start:m.start()] if head_start >= 0 else b''
        yield head, body


def _maybe_inflate(head, body):
    """有 FlateDecode 就尝试解压；失败返回 None。"""
    if b'FlateDecode' in head:
        for trim in (0, 1, 2):        # 有些文件流尾带 \r\n，多试几种
            try:
                return zlib.decompress(body[:len(body) - trim] if trim else body)
            except zlib.error:
                continue
        try:
            return zlib.decompressobj().decompress(body)
        except zlib.error:
            return None
    return body


def _hex_to_bytes(hexstr):
    h = re.sub(rb'[^0-9A-Fa-f]', b'', hexstr)
    if len(h) % 2:
        h += b'0'
    try:
        return bytes.fromhex(h.decode('ascii'))
    except ValueError:
        return b''


def _utf16be(bs):
    try:
        return bs.decode('utf-16-be')
    except UnicodeDecodeError:
        return ''


# ---------------- ToUnicode CMap ----------------

def _parse_cmap(text):
    """解析 ToUnicode CMap，返回 {字符码(int): 文字}。"""
    mapping = {}

    def add_range(lo, hi, dst):
        base = _utf16be(dst) if dst else ''
        if not base:
            return
        for offset in range(0, min(hi - lo + 1, 65536)):
            ch = base
            if offset:
                # 递增最后一个字符（简单近似，够覆盖常见子集）
                ch = base[:-1] + chr(min(0xFFFF, ord(base[-1]) + offset)) if base else ''
            if ch:
                mapping[lo + offset] = ch

    for block in re.findall(rb'beginbfchar(.*?)endbfchar', text, re.S):
        for src, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>', block):
            code = int(src, 16)
            mapping[code] = _utf16be(_hex_to_bytes(dst))

    for block in re.findall(rb'beginbfrange(.*?)endbfrange', text, re.S):
        # 形式一：<lo> <hi> <dst>
        for lo, hi, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>', block):
            add_range(int(lo, 16), int(hi, 16), _hex_to_bytes(dst))
        # 形式二：<lo> <hi> [<d1> <d2> ...]
        for lo, hi, arr in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]', block, re.S):
            base = int(lo, 16)
            for i, d in enumerate(re.findall(rb'<([0-9A-Fa-f]*)>', arr)):
                mapping[base + i] = _utf16be(_hex_to_bytes(d))
    return mapping


# ---------------- 内容流文本提取 ----------------

PRINTABLE = set(range(0x20, 0x7F))


def _decode_bytes(bs, cmap):
    """把 PDF 字符串字节解码成文字：优先 Unicode 映射，其次 UTF-16BE / Latin-1。"""
    if not bs:
        return ''
    # 带 BOM 的 UTF-16
    if bs[:2] == b'\xfe\xff':
        return _utf16be(bs[2:])
    if cmap:
        # CID 字体通常是 2 字节码
        out = []
        for i in range(0, len(bs) - 1, 2):
            code = (bs[i] << 8) | bs[i + 1]
            out.append(cmap.get(code, ''))
        text = ''.join(out)
        if text.strip():
            return text
        # 退一步：单字节码
        single = ''.join(cmap.get(b, '') for b in bs)
        if single.strip():
            return single
    # 纯 ASCII
    if all(b in PRINTABLE or b in (9, 10, 13) for b in bs):
        return bs.decode('latin-1', 'replace')
    if cmap:
        return ''.join(cmap.get(b, '') for b in bs)
    return ''


_ESCAPES = {
    ord('n'): b'\n', ord('r'): b'\r', ord('t'): b'\t',
    ord('b'): b'\b', ord('f'): b'\f',
    ord('('): b'(', ord(')'): b')', ord('\\'): b'\\',
}


def _parse_literal(data, i):
    """从 data[i] 的 '(' 开始解析 PDF 字面量字符串，返回 (bytes, 结束位置)。"""
    out = bytearray()
    depth = 1
    i += 1
    n = len(data)
    while i < n and depth:
        c = data[i]
        if c == 0x5C:                       # 反斜杠转义
            i += 1
            if i >= n:
                break
            e = data[i]
            if e in _ESCAPES:
                out += _ESCAPES[e]
                i += 1
            elif 0x30 <= e <= 0x37:         # 八进制 \ddd
                oct_digits = bytearray()
                for _ in range(3):
                    if i < n and 0x30 <= data[i] <= 0x37:
                        oct_digits.append(data[i])
                        i += 1
                    else:
                        break
                out.append(int(oct_digits.decode() or '0', 8) & 0xFF)
            elif e in (10, 13):             # 续行
                i += 1
                if e == 13 and i < n and data[i] == 10:
                    i += 1
            else:
                out.append(e)
                i += 1
            continue
        if c == 0x28:                       # 嵌套 (
            depth += 1
            out.append(c)
            i += 1
            continue
        if c == 0x29:                       # )
            depth -= 1
            if depth:
                out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return bytes(out), i


_OP_RE = re.compile(rb'(?<![A-Za-z])(Tj|TJ|\'|"|T\*|Td|TD|Tm|ET|BT)(?![A-Za-z])')


def _extract_content_text(content, cmap):
    """从内容流里抽出文字（带换行）。"""
    pieces = []
    i = 0
    n = len(content)
    pending = []            # 当前文本行累积
    while i < n:
        c = content[i]
        if c == 0x28:                                   # ( 字面量
            s, i = _parse_literal(content, i)
            pending.append(_decode_bytes(s, cmap))
            continue
        if c == 0x3C and i + 1 < n and content[i + 1] != 0x3C:   # < 十六进制串
            j = content.find(b'>', i)
            if j < 0:
                break
            pending.append(_decode_bytes(_hex_to_bytes(content[i + 1:j]), cmap))
            i = j + 1
            continue
        if c == 0x5B:                                   # [ … ]TJ 数组
            j = content.find(b']', i)
            if j < 0:
                break
            for m in re.finditer(rb'\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>', content[i:j]):
                seg = m.group(0)
                if seg.startswith(b'('):
                    s, _ = _parse_literal(seg, 0)
                    pending.append(_decode_bytes(s, cmap))
                else:
                    pending.append(_decode_bytes(_hex_to_bytes(seg[1:-1]), cmap))
            i = j + 1
            continue
        m = _OP_RE.match(content, i)
        if m:
            op = m.group(1)
            if op in (b'ET', b'T*', b'Td', b'TD', b'Tm'):
                if pending:
                    pieces.append(''.join(pending))
                    pending = []
            i = m.end()
            continue
        i += 1
    if pending:
        pieces.append(''.join(pending))
    return '\n'.join(p for p in pieces if p.strip())


# ---------------- 对外接口 ----------------

def is_encrypted(raw):
    return b'/Encrypt' in raw[:200000]


def extract(data):
    """从 PDF 字节提取纯文本。失败抛 ValueError（带可读原因）。"""
    if not data:
        raise ValueError('PDF 是空文件')
    if not data[:1024].lstrip().startswith(b'%PDF'):
        raise ValueError('不是有效的 PDF 文件（缺少 %PDF 头）')
    if is_encrypted(data):
        raise ValueError('这个 PDF 已加密，无法解析文本；请在阅读器里另存为未加密版本')

    cmap = {}
    contents = []
    for head, body in _find_streams(data):
        stream = _maybe_inflate(head, body)
        if not stream:
            continue
        if b'beginbfchar' in stream or b'beginbfrange' in stream:
            cmap.update(_parse_cmap(stream))
        elif b'BT' in stream and (b'Tj' in stream or b'TJ' in stream):
            contents.append(stream)

    text_parts = []
    for c in contents:
        t = _extract_content_text(c, cmap)
        if t.strip():
            text_parts.append(t)
        if sum(len(x) for x in text_parts) > MAX_OUTPUT:
            break

    text = '\n\n'.join(text_parts)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    if not text:
        raise ValueError('这个 PDF 没有可提取的文本层（可能是扫描件/图片型 PDF，'
                         '需要 OCR；请改为粘贴文字或用 .docx/.txt）')
    return text[:MAX_OUTPUT]
