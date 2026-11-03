# -*- coding: utf-8 -*-
"""校本资料库：上传本校课件/习题/大纲（.txt/.md/.docx），分块存储，关键词+二元组检索（RAG-lite），
检索结果注入问答、出卷、讲义提示词并标注来源。"""
import re
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET

from . import store


def _extract_docx(raw_bytes):
    """用标准库解析 docx：zipfile + XML 抽取 w:t 文本。"""
    try:
        with zipfile.ZipFile(raw_bytes) as z:
            xml = z.read('word/document.xml')
        root = ET.fromstring(xml)
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paras = []
        for p in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
            text = ''.join(t.text or '' for t in p.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
            if text.strip():
                paras.append(text.strip())
        return '\n'.join(paras)
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return ''


def _clean_text(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _chunk(text, size=420):
    """按段落聚合切块，块大小约 size 字。"""
    paras = [p.strip() for p in text.split('\n') if p.strip()]
    chunks, cur = [], ''
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur = (cur + '\n' + p).strip()
        else:
            if cur:
                chunks.append(cur)
            if len(p) > size * 1.5:
                for i in range(0, len(p), size):
                    chunks.append(p[i:i + size])
                cur = ''
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return chunks


def add_material(sid, name, content, raw_docx=None):
    if raw_docx is not None:
        content = _extract_docx(raw_docx)
    content = _clean_text(content or '')
    if not content:
        return None
    mat = {
        'id': uuid.uuid4().hex[:12],
        'name': (name or '未命名资料')[:80],
        'created': time.time(),
        'size': len(content),
        'text': content,
        'chunks': _chunk(content),
    }
    store.save_material(sid, mat)
    store.log_event(sid, 'material', {'action': 'add', 'name': mat['name'], 'chunks': len(mat['chunks'])})
    return {'id': mat['id'], 'name': mat['name'], 'size': mat['size'], 'chunks': len(mat['chunks'])}


def retrieve(sid, query, top=3):
    """按二元组重合度 + 原文包含加权检索最相关的资料块。"""
    if not query or not query.strip():
        return []
    grams = _grams(query)
    scored = []
    for mat in store.get_materials(sid):
        for idx, chunk in enumerate(mat.get('chunks', [])):
            cg = _grams(chunk)
            score = len(grams & cg) / max(1, len(grams))
            for token in re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,6}', query):
                if token in chunk:
                    score += 0.15
            if score > 0.03:
                scored.append((score, {'text': chunk, 'material': mat['name'], 'chunk_index': idx,
                                       'material_id': mat['id']}))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:top]]


def _grams(text):
    t = re.sub(r'\s+', '', text.lower())
    return set(t[i:i + 2] for i in range(len(t) - 1)) or {t}
