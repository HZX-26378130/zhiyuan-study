# -*- coding: utf-8 -*-
"""AI 知识问答：苏格拉底式引导（含反问）与讲解双模式，覆盖线性代数/数学分析。
支持图片输入（视觉模型读题）、真实联网检索增强、校本资料引用、权威来源、薄弱点更新。"""
import time

from . import knowledge, llm, materials, memory, points, search, store

SYSTEM_PROMPT = (
    '你是一位严谨耐心的大学数学辅导老师，专注线性代数与数学分析。'
    '教学原则：\n'
    '1) 引导优先：不直接抛出完整答案，先带学生一步步推理，每步只前进一步；\n'
    '2) 适当反问：在引导过程中向学生提出1-2个反问（counter_questions），促使学生自己想通关键一步；\n'
    '3) 定位考点：先点明题目考察的知识点；\n'
    '4) 严谨性：数学表述必须严格，引用结论要说明条件；\n'
    '5) 如提供了校本资料摘录或联网检索结果，优先与其一致并标注【校本资料】/【网络资料】；\n'
    '6) 结尾给出可追问的延伸问题。'
)

EXPLAIN_PROMPT = (
    '你是一位严谨耐心的大学数学辅导老师。学生选择了【讲解模式】：'
    '请给出完整、结构化的讲解（定义→思路→完整推导过程→结论→易错点），并附1-2个反问帮助学生自查。'
    '如提供了校本资料摘录或联网检索结果，优先与其一致并标注来源。'
)

ANSWER_SCHEMA = (
    '输出 JSON：{"kp_id": "知识点id或null", "kp_name": "知识点名", '
    '"guidance": ["引导步骤1", "引导步骤2", ...], '
    '"counter_questions": ["反问学生的问题1", "反问2"], '
    '"explanation": "本步的原理说明或完整讲解（markdown，数学用Unicode记号）", '
    '"key_points": ["关键结论"], "followups": ["可追问的问题1", "问题2"], '
    '"sources": [{"title": "资料名", "note": "相关说明或URL"}]}'
)


def _vision_read(image_bytes, mime):
    """视觉模型读题：提取题面文字与图形信息。"""
    prompt = ('这是一道数学题的照片/截图。请完整转录题面文字（数学式用Unicode记号如 ∫ λ ²），'
              '如有图形请描述其数学含义。只输出转录与描述，不要解题。')
    try:
        return llm.chat_vision(prompt, image_bytes, mime)
    except llm.LLMError as e:
        return None


def _prepare(sid, question, subject, image, use_materials, use_web):
    """问答公共前置：视觉读题、考点匹配、资料与联网检索。"""
    image_text = ''
    if image:
        image_text = _vision_read(*image) or ''
    full_question = (question + '\n' + image_text).strip()
    matched = knowledge.match_kps(full_question, subject=subject, top=3)
    kp_ctx = ''
    if matched:
        lines = []
        for s, kp, sc in matched[:2]:
            lines.append('候选考点（%s）：%s —— %s；关键要点：%s'
                         % (knowledge.subjects()[s], kp['name'], kp['description'][:80],
                            '；'.join(kp['key_points'][:3])))
        kp_ctx = '\n'.join(lines)

    mat_chunks = materials.retrieve(sid, full_question, top=3) if use_materials else []
    mat_ctx = ''
    if mat_chunks:
        mat_ctx = '校本资料摘录：\n' + '\n---\n'.join(
            '【%s】%s' % (c['material'], c['text'][:400]) for c in mat_chunks)

    web_results = []
    if use_web and len(full_question) >= 6:
        web_results = search.web_search(full_question[:80], count=4)
    web_ctx = ''
    if web_results:
        web_ctx = '联网检索结果（仅供参考，需甄别）：\n' + '\n'.join(
            '· %s：%s (%s)' % (r['title'], r['snippet'][:150], r['url']) for r in web_results[:3])

    tctx = memory.teaching_context(sid)
    try:
        gctx = memory.global_context()
    except Exception:
        gctx = ''
    return {'image_text': image_text, 'full_question': full_question, 'matched': matched,
            'kp_ctx': kp_ctx, 'mat_chunks': mat_chunks, 'mat_ctx': mat_ctx,
            'web_results': web_results, 'web_ctx': web_ctx, 'tctx': tctx, 'gctx': gctx}


def answer(sid, question, subject=None, mode='guide', image=None, use_materials=True, use_web=True):
    """image: (bytes, mime) 或 None"""
    p = _prepare(sid, question, subject, image, use_materials, use_web)
    image_text, full_question, matched = p['image_text'], p['full_question'], p['matched']
    if image and not image_text and not question.strip():
        return {'error': 'vision_unavailable',
                'message': '当前未配置视觉模型（或识别失败），无法读取图片。请在 config.json 配置 API Key（vision_model 建议 glm-4v-flash），或直接输入文字题目。'}

    mode_prompt = EXPLAIN_PROMPT if mode == 'explain' else SYSTEM_PROMPT

    result = None
    if llm.available():
        user = '\n\n'.join(filter(None, [
            p['gctx'] and '【全班教学上下文（来自所有同学的反馈学习）】\n' + p['gctx'],
            p['tctx'] and '【个性化教学上下文】\n' + p['tctx'],
            p['kp_ctx'] and '【候选考点参考】\n' + p['kp_ctx'],
            p['mat_ctx'],
            p['web_ctx'],
            image_text and '【图片题面转录】\n' + image_text,
            '学生的问题：%s' % (question or '（见图片）'),
            ANSWER_SCHEMA,
        ]))
        try:
            res = llm.chat_json([
                {'role': 'system', 'content': mode_prompt},
                {'role': 'user', 'content': user},
            ], temperature=0.5)
            if res:
                result = _normalize_llm(res, matched, p['mat_chunks'])
        except llm.LLMError:
            result = None
    if result is None:
        result = _offline_answer(full_question, question, matched, p['mat_chunks'], mode, subject)
    return _finalize(sid, question, image, image_text, matched, p['mat_chunks'], p['web_results'], result, mode, subject)


def _finalize(sid, question, image, image_text, matched, mat_chunks, web_results, result, mode, subject):
    kp_ids = [kp['id'] for _, kp, _ in matched]
    # 联网结果并入来源（无论是否离线）
    if web_results:
        result['web_results'] = web_results[:4]
        result.setdefault('sources', [])
        result['sources'] += [{'title': '🌐 ' + r['title'], 'note': r['url']} for r in web_results[:3]]

    # 更新薄弱点画像
    for s, kp, _ in matched[:1]:
        store.update_mastery(sid, kp['id'], s, 2)
    # 档案可能不存在（前端 localStorage 里的旧 sid / 已删除的档案）：
    # 画像缺失只跳过统计，不能让整次问答 500
    prof = store.get_profile(sid)
    if prof is not None:
        prof.setdefault('stats', {})
        prof['stats']['qa'] = prof['stats'].get('qa', 0) + 1
        store.save_profile(sid, prof)
    store.log_event(sid, 'qa', {'q': (question or '[图片题]')[:200], 'kps': kp_ids, 'mode': mode,
                                'has_image': bool(image),
                                'offline': result.get('offline', False), 'ts': time.time()})
    result['awarded'] = points.notify(sid, 'qa')

    links = search.source_links(result.get('kp_name') or (question or '数学')[:20], subject=subject)
    result.setdefault('sources', [])
    result['sources'] += [{'title': l['title'], 'note': l['url']} for l in links[:3]]
    result['material_refs'] = [{'material': c['material'], 'text': c['text'][:150]} for c in mat_chunks]
    result['matched_kps'] = [{'id': kp['id'], 'name': kp['name'], 'subject': s} for s, kp, _ in matched]
    if image and not result.get('image_note'):
        result['image_note'] = '已接收图片' + ('，视觉模型转录见引导内容' if image_text else '（离线模式无法识别图片文字）')
    return result


STREAM_SCHEMA = (
    '为了让回答能被边生成边显示，请严格按以下分节输出（每个标题单独成行，不要输出JSON、不要用代码围栏）：\n'
    '【引导】\n- 引导步骤1\n- 引导步骤2\n'
    '【反问】\n- 反问1\n'
    '【讲解】\n（完整讲解，markdown，公式用 $...$）\n'
    '【要点】\n- 关键结论1\n- 关键结论2\n'
    '【追问】\n- 可追问的问题1\n- 可追问的问题2'
)

_SECTIONS = ('引导', '反问', '讲解', '要点', '追问')


def _parse_sections(text, matched):
    """解析分节输出为结构化结果；模型未按格式时整体降级为讲解。"""
    import re
    sec, cur = {}, None
    for line in text.splitlines():
        m = re.match(r'^\s*[【\[]\s*(' + '|'.join(_SECTIONS) + r')\s*[】\]]\s*$', line.strip())
        if m:
            cur = m.group(1)
            sec[cur] = []
        elif cur:
            sec[cur].append(line)

    def bullets(name):
        out = []
        for l in sec.get(name, []):
            l2 = l.strip().lstrip('-*·•　 ').strip()
            if l2:
                out.append(l2[:300])
        return out

    explanation = '\n'.join(sec.get('讲解', [])).strip()
    if not explanation:
        explanation = text.strip()[:3000]
    return {
        'kp_name': matched[0][1]['name'] if matched else '',
        'guidance': bullets('引导'),
        'counter_questions': bullets('反问'),
        'explanation': explanation,
        'key_points': bullets('要点'),
        'followups': bullets('追问'),
        'sources': [],
        'offline': False,
    }


def answer_stream(sid, question, subject=None, mode='guide', image=None,
                  use_materials=True, use_web=True, on_delta=None):
    """流式问答：AI 输出通过 on_delta(chunk) 逐段回调（SSE 用），返回结构与 answer() 一致。"""
    p = _prepare(sid, question, subject, image, use_materials, use_web)
    image_text, full_question, matched = p['image_text'], p['full_question'], p['matched']
    if image and not image_text and not question.strip():
        return {'error': 'vision_unavailable',
                'message': '当前未配置视觉模型（或识别失败），无法读取图片。'}

    mode_prompt = EXPLAIN_PROMPT if mode == 'explain' else SYSTEM_PROMPT
    result = None
    if llm.available():
        user = '\n\n'.join(filter(None, [
            p['gctx'] and '【全班教学上下文（来自所有同学的反馈学习）】\n' + p['gctx'],
            p['tctx'] and '【个性化教学上下文】\n' + p['tctx'],
            p['kp_ctx'] and '【候选考点参考】\n' + p['kp_ctx'],
            p['mat_ctx'],
            p['web_ctx'],
            image_text and '【图片题面转录】\n' + image_text,
            '学生的问题：%s' % (question or '（见图片）'),
            STREAM_SCHEMA,
        ]))
        try:
            full = llm.chat_stream([
                {'role': 'system', 'content': mode_prompt},
                {'role': 'user', 'content': user},
            ], on_delta=on_delta, temperature=0.5, max_tokens=4000)
            if full:
                result = _parse_sections(full, matched)
        except llm.LLMError:
            result = None
    if result is None:
        result = _offline_answer(full_question, question, matched, p['mat_chunks'], mode, subject)
        if on_delta:
            on_delta(result.get('explanation', ''))
    return _finalize(sid, question, image, image_text, matched, p['mat_chunks'], p['web_results'], result, mode, subject)


def _normalize_llm(res, matched, mat_chunks):
    return {
        'kp_name': res.get('kp_name') or (matched[0][1]['name'] if matched else ''),
        'guidance': [g for g in res.get('guidance', []) if isinstance(g, str)],
        'counter_questions': [g for g in res.get('counter_questions', []) if isinstance(g, str)],
        'explanation': res.get('explanation', ''),
        'key_points': [k for k in res.get('key_points', []) if isinstance(k, str)],
        'followups': [f for f in res.get('followups', []) if isinstance(f, str)],
        'sources': [{'title': s.get('title', ''), 'note': s.get('note', '')}
                    for s in res.get('sources', []) if isinstance(s, dict)],
        'offline': False,
    }


def _offline_answer(full_question, question, matched, mat_chunks, mode, subject):
    """离线演示：内置知识图谱拼装；含反问；未命中时用通用证明题引导 + 开源题库/资料索引。"""
    src_hits = search.match_sources(full_question, top=3)
    if not matched:
        base = knowledge.generic_guidance(subject)
        explanation = base['explanation']
        if src_hits:
            explanation += '\n\n【相关开源资料/题库】\n' + '\n'.join(
                '· %s：%s' % (s['name'], s['url']) for s in src_hits)
        if mat_chunks:
            explanation = '【校本资料相关片段】\n' + mat_chunks[0]['text'][:200] + '\n\n' + explanation
        base['sources'] = [{'title': s['name'], 'note': s['url']} for s in src_hits]
        base['offline'] = True
        base['counter_questions'] = base['followups']
        return base
    s, kp, _ = matched[0]
    guidance = ['这道题主要考察《%s》中的【%s】。' % (knowledge.subjects()[s], kp['name'])]
    guidance += ['想一想：%s' % kpt for kpt in kp['key_points'][:3]]
    counter = []
    if mode != 'explain':
        guidance.append('先按上面第1条要点写出定义或公式，再对照第2条检查条件是否满足。')
        if kp['samples']:
            counter.append('不看答案的话，你觉得这道题第一步应该把哪个量孤立出来？为什么？')
        counter.append('这道题的条件里，哪一个最容易被忽略？它排除了什么情况？')
    sample = kp['samples'][0]
    explanation = '【原理】%s\n\n【易错点】\n%s\n\n【同类例题】%s\n【参考解法】%s' % (
        kp['description'],
        '\n'.join('· ' + e for e in kp['common_errors']),
        sample['q'], sample['a'],
    )
    if mat_chunks:
        explanation = '【校本资料相关片段】\n' + mat_chunks[0]['text'][:200] + '\n\n' + explanation
    if src_hits:
        explanation += '\n\n【相关开源资料/题库】\n' + '\n'.join('· %s：%s' % (x['name'], x['url']) for x in src_hits)
    return {
        'kp_name': kp['name'],
        'guidance': guidance,
        'counter_questions': counter,
        'explanation': explanation,
        'key_points': kp['key_points'][:4],
        'followups': ['%s 与前置知识「%s」的联系是什么？' % (kp['name'], knowledge.get_kp(s, p)['name'])
                      for p in kp.get('prereqs', [])[:2] if knowledge.get_kp(s, p)],
        'sources': [{'title': r['title'], 'note': r.get('url', '')} for r in kp['refs'] if r.get('title')],
        'offline': True,
    }
