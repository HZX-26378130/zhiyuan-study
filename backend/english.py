# -*- coding: utf-8 -*-
"""英语批改引擎：CET 作文/段落翻译。LLM 精批（对标评分标准逐句改错+范文）；
无 Key 时启发式批改（规则库 + 内置范文/参考译文对照）。"""
import json
import os
import re
import time

from . import llm, memory, points, store, wrongbook

DATA = store.DATA_DIR

_CACHE = {}


def _load(rel):
    if rel not in _CACHE:
        with open(os.path.join(DATA, rel), encoding='utf-8') as f:
            _CACHE[rel] = json.load(f)
    return _CACHE[rel]


def rubric_writing():
    return _load('rubrics/cet_writing.json')


def rubric_translation():
    return _load('rubrics/cet_translation.json')


def bank():
    return _load('bank/english_bank.json')


def list_prompts(level=None):
    out = []
    for p in bank()['writing_prompts']:
        if level and p.get('level') != level:
            continue
        out.append({'id': p['id'], 'level': p['level'], 'topic_cn': p['topic_cn'],
                    'year': p.get('year', ''), 'tag': p.get('tag', '自编'),
                    'directions': p['directions'][:120] + '…'})
    return out


def get_prompt(pid):
    for p in bank()['writing_prompts']:
        if p['id'] == pid:
            return p
    return None


def get_translation_item(tid):
    for t in bank()['translation_items']:
        if t['id'] == tid:
            return t
    return None


def list_translation_items(level=None):
    return [{'id': t['id'], 'level': t['level'], 'year': t.get('year', ''),
             'tag': t.get('tag', '自编'), 'topic': t.get('topic', t['source_cn'][:20]),
             'source_cn': t['source_cn'][:40] + '…'}
            for t in bank()['translation_items'] if not level or t.get('level') == level]


def _transcribe_essay(image_bytes, mime):
    """视觉模型转录手写作文/译文：要求逐词保留原样（含拼写错误），供批改。"""
    prompt = ('这是一张英语作文/翻译答卷的照片。请逐词转录为纯文本（保留原有拼写错误、标点与分段，'
              '不要修正、不要批注、不要添加解释），只输出转录文本本身。')
    try:
        return llm.chat_vision(prompt, image_bytes, mime)
    except llm.LLMError:
        return None


# ============ LLM 精批 ============

def _llm_grade(sid, kind, text, level, prompt_ctx):
    tctx = memory.teaching_context(sid)
    if kind == 'writing':
        rub = rubric_writing()
        bands = '\n'.join('%s分档：%s' % (b['band'], b['desc']) for b in rub['bands'])
        spec = ('这是大学英语%s作文批改任务。评分标准（15分制）：%s\n字数要求：%d-%d词。'
                % (level.upper(), bands, *rub['word_count'][level]))
    else:
        rub = rubric_translation()
        bands = '\n'.join('%s分档：%s' % (b['band'], b['desc']) for b in rub['bands'])
        spec = '这是大学英语%s段落翻译批改任务。评分标准（15分制）：%s' % (level.upper(), bands)
    user = '\n\n'.join(filter(None, [
        tctx and '【个性化教学上下文】\n' + tctx,
        prompt_ctx,
        spec,
        '学生答案：\n' + text,
        '输出 JSON：{"score": 0-15数字, "band_desc": "所在档位描述", '
        '"dims": [{"name": "维度名", "score": "该维度得分或评价", "comment": "点评"}], '
        '"corrections": [{"original": "原句片段", "revised": "改后", "type": "语法/用词/搭配/拼写", "note": "错误原因"}], '
        '"strengths": ["亮点1", "亮点2"], '
        '"model_essay": "针对同一题目的完整范文（翻译题则为参考译文优化版）", '
        '"phrases": [{"en": "地道表达", "cn": "含义"}], '
        '"summary": "总体评价与提分建议（150字内）"}',
    ]))
    res = llm.chat_json([
        {'role': 'system', 'content': '你是大学英语四六级阅卷老师，按评分标准严格批改，逐句指出语言错误并给出修改，讲解要具体到语法点。'},
        {'role': 'user', 'content': user},
    ], temperature=0.3)
    if not res:
        return None
    return {
        'score': res.get('score'), 'band_desc': res.get('band_desc', ''),
        'dims': res.get('dims', []), 'corrections': res.get('corrections', []),
        'strengths': res.get('strengths', []), 'model_essay': res.get('model_essay', ''),
        'phrases': res.get('phrases', []), 'summary': res.get('summary', ''),
        'offline': False,
    }


# ============ 离线启发式批改 ============

_RULES = [
    (re.compile(r'\bI\s+very\s+(like|love|enjoy)\b', re.I), 'I ~ very much', '中式语序：very much 后置'),
    (re.compile(r'\bthere\s+(have|has)\b', re.I), 'there is/are …', 'there be 句型误用 have'),
    (re.compile(r'\bmore\s+and\s+more\s+people\s+begin\b', re.I), 'an increasing number of people', '提升表达多样性'),
    (re.compile(r'\bwith\s+the\s+develop(ment)?\s+of\s+the?\s*so?ciety\b', re.I), 'with the development of society', '多余冠词/搭配'),
    (re.compile(r'\bplays?\s+an?\s+important\s+role\s+in\s+(the\s+)?our\b', re.I), 'plays an important role in our …', '冠词重复'),
    (re.compile(r'\bin\s+the\s+other\s+hand\b', re.I), 'on the other hand', '介词搭配错误'),
    (re.compile(r'\bas\s+we\s+all\s+knows\b', re.I), 'as we all know', '主谓一致'),
    (re.compile(r'\bpeoples?\s+is\b', re.I), 'people are', '主谓一致（people复数）'),
    (re.compile(r'\bcan\s+to\s+\w+', re.I), 'can do', '情态动词后接原形'),
    (re.compile(r'\bevery\s+days\b', re.I), 'every day', '固定搭配'),
    (re.compile(r'\bdo\s+a\s+decision\b', re.I), 'make a decision', '动词搭配'),
    (re.compile(r'\blearn\s+knowledges?\b', re.I), 'acquire knowledge', 'knowledge 不可数，搭配 learn→acquire'),
    (re.compile(r'\bin\s+my\s+opinion\s*,\s*I\s+think\b', re.I), 'in my opinion, …（去掉 I think）', '语义重复'),
    (re.compile(r'\baccording\s+to\s+me\b', re.I), 'in my view', 'according to 不能接 me'),
]

_CONN = re.compile(r'\b(furthermore|moreover|however|therefore|in addition|on the one hand|to begin with|in conclusion|nevertheless)\b', re.I)


def _heuristic_writing(text, level, prompt_obj):
    words = re.findall(r"[A-Za-z']+", text)
    wc = len(words)
    sents = [s for s in re.split(r'[.!?]+', text) if s.strip()]
    sc = max(1, len(sents))
    avg_len = wc / sc
    types = set(w.lower() for w in words)
    ttr = len(types) / max(1, wc)
    lo, hi = rubric_writing()['word_count'][level]
    corrections = []
    for pat, fix, note in _RULES:
        for m in pat.finditer(text):
            corrections.append({'original': m.group(0), 'revised': fix, 'type': '语法/表达', 'note': note})
    if not text.rstrip().endswith(('.', '!', '?')):
        corrections.append({'original': '结尾', 'revised': '补全末句标点', 'type': '格式', 'note': '作文应有完整句末标点'})
    if re.search(r'[\u4e00-\u9fff]', text):
        corrections.append({'original': '（含中文）', 'revised': '全英作答', 'type': '格式', 'note': '作文中混入了中文'})

    score = 8.0
    if wc < lo * 0.9:
        score -= 2
    elif lo <= wc <= hi:
        score += 1
    if avg_len >= 12:
        score += 1
    if avg_len < 7 and wc > 40:
        score -= 1
    if ttr > 0.55:
        score += 1
    if _CONN.search(text):
        score += 0.5
    score = max(2, min(13, score - len(corrections) * 0.5))
    score = round(score)

    band = next(b for b in rubric_writing()['bands'] if b['range'][0] <= score <= b['range'][1])
    model = ''
    phrases = []
    tips = []
    if prompt_obj:
        model = prompt_obj['model_essay']
        phrases = [{'en': e.split('  ')[0], 'cn': e.split('  ')[-1] if '  ' in e else ''}
                   for e in prompt_obj['useful_expressions']]
        tips = ['题目方向：%s' % prompt_obj['directions'][:80]]
    dims = [
        {'name': '内容与切题', 'score': '—', 'comment': '离线模式仅作统计参考：词数 %d（要求 %d-%d）' % (wc, lo, hi)},
        {'name': '语言质量', 'score': str(len(corrections)) + '处疑似问题', 'comment': '平均句长 %.1f 词；词汇丰富度 %.2f' % (avg_len, ttr)},
        {'name': '结构与衔接', 'score': '—', 'comment': '检测到衔接词' if _CONN.search(text) else '建议增加 Firstly/Moreover/In conclusion 等衔接词'},
    ]
    summary = ('【离线启发式批改】词数 %d、句子 %d、平均句长 %.1f、衔接词 %s。检测到 %d 处疑似语言问题（见逐条修改）。'
               '配置大模型 API Key 后可获得对标评分标准的逐句精批与定制范文。'
               % (wc, sc, avg_len, '有' if _CONN.search(text) else '较少', len(corrections)))
    return {'score': score, 'band_desc': band['desc'], 'dims': dims, 'corrections': corrections,
            'strengths': (['字数达标'] if lo <= wc <= hi else []) + (['使用了衔接词'] if _CONN.search(text) else []),
            'model_essay': model, 'phrases': phrases, 'summary': summary, 'offline': True}


def _heuristic_translation(text, level, item):
    words = re.findall(r"[A-Za-z']+", text)
    wc = len(words)
    corrections = []
    for pat, fix, note in _RULES:
        for m in pat.finditer(text):
            corrections.append({'original': m.group(0), 'revised': fix, 'type': '语法/表达', 'note': note})
    if re.search(r'[\u4e00-\u9fff]', text):
        corrections.append({'original': '（含中文）', 'revised': '全英翻译', 'type': '格式', 'note': '译文中混入了中文'})
    coverage = 0.0
    ref = item['reference_en'] if item else ''
    if item and ref:
        ref_tokens = set(w.lower() for w in re.findall(r"[A-Za-z']+", ref))
        hit = sum(1 for w in set(w.lower() for w in words) if w in ref_tokens)
        coverage = hit / max(1, len(ref_tokens))
        for kp in item.get('key_points', []):
            en = kp.split(' ')[0:2]
            if not any(p.lower() in text.lower() for p in [' '.join(en[:1])]):
                corrections.append({'original': '关键词缺失', 'revised': kp, 'type': '信息点', 'note': '参考译文使用了该表达'})
    score = round(max(3, min(13, 6 + coverage * 8 - len(corrections) * 0.4)))
    band = next(b for b in rubric_translation()['bands'] if b['band'][0].isdigit())
    bands = rubric_translation()['bands']
    band = bands[1] if score >= 10 else (bands[2] if score >= 7 else (bands[3] if score >= 4 else bands[4]))
    dims = [
        {'name': '忠实原文', 'score': '—', 'comment': '与参考译文词汇重合度 %.0f%%' % (coverage * 100)},
        {'name': '语言质量', 'score': str(len(corrections)) + '处疑似问题', 'comment': '译文字数 %d' % wc},
        {'name': '表达地道', 'score': '—', 'comment': '离线模式给统计参考'},
    ]
    summary = ('【离线启发式批改】与参考译文词汇重合度约 %.0f%%，检出 %d 处疑似问题。'
               '参考译文与关键表达见下方。配置 API Key 可获得逐句精批。' % (coverage * 100, len(corrections)))
    return {'score': score, 'band_desc': band['desc'], 'dims': dims, 'corrections': corrections,
            'strengths': ['完成了翻译任务'], 'model_essay': ref, 'phrases': [
                {'en': kp.split(' ')[0], 'cn': kp[len(kp.split(' ')[0]):].strip()} for kp in (item.get('key_points', []) if item else [])],
            'summary': summary, 'offline': True}


# ============ 入口 ============

def grade(sid, kind, text, level='cet4', prompt_id=None, image=None):
    kind = kind if kind in ('writing', 'translation') else 'writing'
    level = level if level in ('cet4', 'cet6') else 'cet4'
    image_text = ''
    if image and (not text or len(text) < 20):
        image_text = _transcribe_essay(*image) or ''
        if not image_text:
            return {'error': 'vision_unavailable',
                    'message': '无法识别图片（需配置视觉模型，如 glm-4v-flash），或直接输入文字后批改。'}
        text = image_text
    if len(text.strip()) < 10:
        raise ValueError('答案太短，无法批改')
    item = None
    if kind == 'writing':
        p = get_prompt(prompt_id) if prompt_id else None
        prompt_ctx = ('题目：%s\n' % p['directions']) if p else ''
        result = None
        if llm.available():
            try:
                result = _llm_grade(sid, kind, text, level, prompt_ctx)
            except llm.LLMError:      # 模型不可用（欠费/限流/断网）→ 静默降级到离线启发式批改
                result = None
        if result is None:
            result = _heuristic_writing(text, level, p)
        if p:
            result['year'] = p.get('year', '')
            result['tag'] = p.get('tag', '')
    else:
        item = get_translation_item(prompt_id) if prompt_id else None
        prompt_ctx = ('原文：\n%s\n' % item['source_cn']) if item else ''
        if item:
            prompt_ctx += '关键表达（评分参考）：%s\n' % '；'.join(item['key_points'])
        result = None
        if llm.available():
            try:
                result = _llm_grade(sid, kind, text, level, prompt_ctx)
            except llm.LLMError:      # 同上：批改永不因模型故障而 500
                result = None
        if result is None:
            result = _heuristic_translation(text, level, item)
        if item:
            result['year'] = item.get('year', '')
            result['tag'] = item.get('tag', '')
    if image:
        result['image_note'] = '图片已识别' if image_text else '（图片已保存，未启用视觉识别）'

    # 薄弱点画像：英语作为伪知识点
    kp_id = 'en_%s' % kind
    delta = +3 if (result.get('score') or 0) >= 10 else (+1 if (result.get('score') or 0) >= 7 else -2)
    store.update_mastery(sid, kp_id, 'english', delta, wrong=delta < 0)
    prof = store.get_profile(sid)
    prof['stats']['graded'] = prof.get('stats', {}).get('graded', 0) + 1
    store.save_profile(sid, prof)
    store.log_event(sid, 'english', {'kind': kind, 'score': result.get('score'),
                                     'summary': result.get('summary', '')[:150],
                                     'offline': result.get('offline'), 'ts': time.time()})
    result['awarded'] = points.notify(sid, 'english')
    # 错题本：批改发现的错误自动归类
    for c in (result.get('corrections') or [])[:5]:
        wrongbook.add(sid, 'english', c.get('type', '语言'),
                      stem=(c.get('original', '') + ' → ' + c.get('revised', '')),
                      your=c.get('original', ''), answer=c.get('revised', ''),
                      note=c.get('note', ''), subject='english', ref=kind)
    return result
