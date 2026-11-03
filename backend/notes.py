# -*- coding: utf-8 -*-
"""薄弱点讲义：为选定知识点生成个性化讲义（概念精讲/典型例题/易错警示/巩固练习/参考资料），
可结合校本资料，输出 Markdown 供导出打印。"""
import time

from . import knowledge, llm, materials, points, store


def generate(sid, subject, kp_ids, include_materials=True):
    sub = knowledge.get_subject(subject)
    if not sub:
        return {'error': '未知科目'}
    kp_ids = [k for k in (kp_ids or knowledge.recommend_kps(sid, subject, n=3)) if k in sub['kps']]
    if not kp_ids:
        return {'error': '请选择知识点'}

    kps = [sub['kps'][k] for k in kp_ids]
    mat_chunks = []
    if include_materials:
        mat_chunks = materials.retrieve(sid, ' '.join(kp['name'] for kp in kps), top=3)

    title = '《%s》薄弱点讲义：%s' % (sub['name'], '、'.join(kp['name'] for kp in kps))
    md, offline = None, True
    if llm.available():
        md = _llm_notes(subject, kps, mat_chunks)
        offline = md is None
    if not md:
        md = _offline_notes(subject, kps, mat_chunks)
        offline = True

    doc = {'id': ('n%s' % time.time_ns())[-12:], 'created': time.time(),
           'title': title, 'subject': subject, 'kps': kp_ids, 'markdown': md,
           'offline': offline}
    store.save_note(sid, doc['id'], doc)
    prof = store.get_profile(sid)
    prof['stats']['notes'] = prof.get('stats', {}).get('notes', 0) + 1
    store.save_profile(sid, prof)
    store.log_event(sid, 'notes', {'note_id': doc['id'], 'kps': kp_ids})
    doc['awarded'] = points.notify(sid, 'notes')
    return {k: doc[k] for k in ('id', 'created', 'title', 'subject', 'kps', 'markdown', 'offline', 'awarded') if k in doc}


def _llm_notes(subject, kps, mat_chunks):
    ctx = []
    for kp in kps:
        ctx.append('【%s】%s\n要点：%s\n易错：%s\n内置例题：%s（%s）'
                   % (kp['name'], kp['description'][:120],
                      '；'.join(kp['key_points']), '；'.join(kp['common_errors']),
                      kp['samples'][0]['q'], kp['samples'][0]['a'][:100]))
    user = '\n\n'.join(filter(None, [
        '为以下知识点编写一份大学讲义（Markdown），面向薄弱学生：\n\n' + '\n\n'.join(ctx),
        ('请优先引用校本资料中的表述与例题：\n' + '\n'.join('【%s】%s' % (c['material'], c['text'][:250]) for c in mat_chunks)) if mat_chunks else '',
        '结构要求：每个知识点一节，含「概念精讲」「关键定理与方法」「典型例题（含完整解答）」「易错警示」「巩固练习（2题，文末给答案）」；'
        '开头有本讲学习目标，结尾有「资料来源」。数学记号用 Unicode（如 ∫ Σ λ⁻¹），不要用 LaTeX 反斜杠命令。',
    ]))
    try:
        return llm.chat([{'role': 'system', 'content': '你是编写大学教材讲义的资深教师，讲解严谨、循序渐进。'},
                         {'role': 'user', 'content': user}], temperature=0.4, max_tokens=6000)
    except llm.LLMError:
        return None


def _offline_notes(subject, kps, mat_chunks):
    lines = ['# 薄弱点讲义（离线模式）', '']
    lines.append('> 本讲义由内置知识图谱自动拼装；配置大模型 API Key 后可生成更详尽的定制讲义。')
    lines.append('')
    lines.append('## 学习目标')
    for kp in kps:
        lines.append('- 掌握「%s」的核心方法与典型易错点' % kp['name'])
    lines.append('')
    for kp in kps:
        lines.append('## %s' % kp['name'])
        lines.append('')
        lines.append('### 概念精讲')
        lines.append(kp['description'])
        lines.append('')
        lines.append('### 关键要点')
        for p in kp['key_points']:
            lines.append('- ' + p)
        lines.append('')
        lines.append('### 典型例题')
        for i, s in enumerate(kp['samples'], 1):
            lines.append('**例%d（%s）** %s' % (i, '计算' if s['type'] == 'compute' else '概念', s['q']))
            lines.append('')
            lines.append('解：%s' % s['a'])
            lines.append('')
        lines.append('### 易错警示')
        for e in kp['common_errors']:
            lines.append('- ⚠️ ' + e)
        lines.append('')
    if mat_chunks:
        lines.append('### 校本资料摘录')
        for c in mat_chunks:
            lines.append('- 【%s】%s…' % (c['material'], c['text'][:180]))
        lines.append('')
    lines.append('### 资料来源')
    for kp in kps:
        for r in kp['refs']:
            if r.get('title'):
                lines.append('- %s%s' % (r['title'], ('：' + r['url']) if r.get('url') else ''))
    return '\n'.join(lines)
