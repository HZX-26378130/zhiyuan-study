# -*- coding: utf-8 -*-
"""PDF 文本提取回归测试（纯离线，自己拼 PDF 字节，不依赖任何第三方库）。

用法：py -3 scripts/test_pdftext.py
覆盖：
  1. 未压缩内容流：能抽出英文文本
  2. FlateDecode 压缩内容流：能解压后抽出文本
  3. ToUnicode CMap 映射：能还原中文（CID 字体常见做法）
  4. 多页：两页文本都要在结果里
  5. 加密 PDF：给出「已加密」的中文提示
  6. 没有文本层的（只有图片）：给出「扫描件/图片型」提示
  7. 非 PDF 文件：给出「不是有效 PDF」
  8. 接入 materials：PDF 能进校本资料库并参与检索
"""
import os
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _console import utf8
    utf8()
except Exception:  # noqa: BLE001
    pass

_tmp = tempfile.mkdtemp(prefix='zy_pdf_')
for _sub in ('vocab', 'knowledge', 'bank', 'rubrics'):
    _src = os.path.join(ROOT, 'data', _sub)
    if os.path.isdir(_src):
        import shutil
        shutil.copytree(_src, os.path.join(_tmp, 'data', _sub))
os.environ['ZY_DATA_DIR'] = os.path.join(_tmp, 'data')

from backend import pdftext  # noqa: E402

fails = []


def check(cond, msg):
    print('[%s] %s' % ('OK' if cond else 'FAIL', msg))
    if not cond:
        fails.append(msg)


# ---------------- 构造 PDF 的小工具 ----------------

def make_pdf(streams, extra_objs=(), encrypted=False, no_text=False):
    """streams: [(content_bytes, compress:bool)]，生成最小可解析 PDF。"""
    objs = []
    if encrypted:
        objs.append(b'<< /Filter /Standard >>')
    for i, (content, compress) in enumerate(streams):
        if compress:
            body = zlib.compress(content)
            objs.append(b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(body) + body + b'\nendstream')
        else:
            objs.append(b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream')
    objs.extend(extra_objs)
    out = [b'%PDF-1.4\n']
    for i, o in enumerate(objs):
        out.append(b'%d 0 obj\n' % (i + 1) + o + b'\nendobj\n')
    if encrypted:
        # 真实 PDF 的加密标记在 trailer 的 /Encrypt 里
        out.append(b'trailer\n<< /Root 1 0 R /Encrypt %d 0 R >>\n' % (len(objs) + 1))
    out.append(b'%%EOF\n')
    return b''.join(out)


# ---------------- 1. 未压缩英文 ----------------
data = make_pdf([(b'BT /F1 12 Tf 20 100 Td (Hello ZhiYuan Study) Tj ET', False)])
text = pdftext.extract(data)
check('Hello ZhiYuan Study' in text, '未压缩流：抽出英文 %r' % text)

# ---------------- 2. FlateDecode ----------------
data = make_pdf([(b'BT /F1 12 Tf (Compressed Line One) Tj T* (Second Line) Tj ET', True)])
text = pdftext.extract(data)
check('Compressed Line One' in text and 'Second Line' in text,
      'FlateDecode 流：解压并抽出两行')

# ---------------- 3. ToUnicode CMap 还原中文 ----------------
cmap = (
    b'/CIDInit /ProcSet findresource begin\n'
    b'begincmap\n1 begincodespacerange <0000> <FFFF> endcodespacerange\n'
    b'2 beginbfchar\n<0001> <4E2D>\n<0002> <6587>\nendbfchar\n'
    b'1 beginbfrange\n<0010> <0012> <0041>\nendbfrange\n'
    b'endcmap\n'
)
content = b'BT /F1 12 Tf <0001> Tj <0002> Tj ET'
data = make_pdf([(content, False), (cmap, True)])
text = pdftext.extract(data)
check('中文' in text, 'ToUnicode CMap：<0001><0002> → 中文（实际 %r）' % text)

# bfrange 形式
content = b'BT <0010> Tj <0011> Tj <0012> Tj ET'
data = make_pdf([(content, False), (cmap, True)])
text = pdftext.extract(data)
check('ABC' in text.replace(' ', ''), 'bfrange 连续码位：→ ABC（实际 %r）' % text)

# ---------------- 4. 多页 ----------------
data = make_pdf([
    (b'BT (Page One Text) Tj ET', False),
    (b'BT (Page Two Text) Tj ET', True),
])
text = pdftext.extract(data)
check('Page One Text' in text and 'Page Two Text' in text, '多页：两页文本都在结果里')

# ---------------- 5. 加密 ----------------
data = make_pdf([(b'BT (secret) Tj ET', False)], encrypted=True)
try:
    pdftext.extract(data)
    check(False, '加密 PDF 应报错')
except ValueError as e:
    check('加密' in str(e), '加密 PDF：提示「%s」' % str(e)[:24])

# ---------------- 6. 没有文本层 ----------------
data = make_pdf([(b'q 200 0 0 200 0 0 cm /Im0 Do Q', False)])
try:
    pdftext.extract(data)
    check(False, '无文本层应报错')
except ValueError as e:
    check('扫描' in str(e) or 'OCR' in str(e), '纯图片 PDF：提示「%s」' % str(e)[:28])

# ---------------- 7. 非 PDF ----------------
try:
    pdftext.extract(b'just a text file')
    check(False, '非 PDF 应报错')
except ValueError as e:
    check('PDF' in str(e), '非 PDF 文件：提示「%s」' % str(e)[:20])

# ---------------- 8. 接入材料库 ----------------
try:
    from backend import materials, store
    sid, _ = store.create_student('PDF 测试生')
    pdf_bytes = make_pdf([(b'BT (Linear algebra final exam key points) Tj ET', True)])
    txt = pdftext.extract(pdf_bytes)
    r = materials.add_material(sid, '线代期末重点', txt)
    check(bool(r and r.get('chunks', 0) >= 1), 'PDF 文本可入库（%s 块）' % (r or {}).get('chunks'))
    hits = materials.retrieve(sid, 'linear algebra exam', top=3)
    check(bool(hits) and any('exam' in (h.get('text') or '').lower() for h in hits),
          '入库后可被检索到')
except Exception as e:  # noqa: BLE001
    check(False, '材料库链路异常: %r' % (e,))

print()
if fails:
    print('%d 项失败' % len(fails))
    sys.exit(1)
print('全部通过 ✓')
