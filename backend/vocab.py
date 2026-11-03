# -*- coding: utf-8 -*-
"""四六级词汇检测：基于开源词库（KyleBing/english-vocabulary，GitHub）。
选择题出题（错误词加权重出），生词本自动积累，配 LLM 时可生成语境例句填空题。"""
import json
import os
import random
import time

from . import llm, points, store, wrongbook

DATA = store.DATA_DIR
_WORDLISTS = {}


def _words(level):
    if level not in _WORDLISTS:
        path = os.path.join(DATA, 'vocab', '%s.json' % level)
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        clean = []
        for w in raw:
            trans = (w.get('translations') or [{}])[0]
            meaning = trans.get('translation', '')
            if not meaning or not w.get('word'):
                continue
            clean.append({'word': w['word'].strip().lower(),
                          'meaning': meaning,
                          'pos': trans.get('type', ''),
                          'phrase': (w.get('phrases') or [{}])[0].get('phrase', '')})
        _WORDLISTS[level] = clean
    return _WORDLISTS[level]


def _pick_words(sid, level, count):
    """生词本中答错过的词优先（60%），其余随机。"""
    pool = _words(level)
    by_word = {w['word']: w for w in pool}
    prof = store.get_profile(sid) or {}
    wb = {k: v for k, v in prof.get('wordbook', {}).items() if v.get('level') == level}
    wrong_sorted = sorted(wb.items(), key=lambda x: -(x[1].get('wrong', 0) - x[1].get('right', 0) * 0.5))
    chosen, seen = [], set()
    for word, _info in wrong_sorted:
        if len(chosen) >= max(1, int(count * 0.6)):
            break
        if word in by_word and word not in seen:
            chosen.append(by_word[word])
            seen.add(word)
    while len(chosen) < count:
        w = random.choice(pool)
        if w['word'] not in seen:
            chosen.append(w)
            seen.add(w['word'])
    return chosen[:count]


def _make_choice(item, level):
    pool = _words(level)
    distractors = []
    tries = 0
    while len(distractors) < 3 and tries < 100:
        cand = random.choice(pool)
        tries += 1
        if cand['meaning'] != item['meaning'] and cand['meaning'] not in [d['meaning'] for d in distractors]:
            distractors.append(cand)
    options = [{'key': 'ABCD'[i], 'meaning': d['meaning'], 'pos': d['pos']}
               for i, d in enumerate(distractors + [item])]
    random.shuffle(options)
    for i, opt in enumerate(options):
        opt['key'] = 'ABCD'[i]
        if opt['meaning'] == item['meaning']:
            answer_key = 'ABCD'[i]
    return {'word': item['word'], 'pos': item['pos'], 'phrase': item['phrase'],
            'options': options, 'answer': answer_key}


QUIZ_CACHE = {}  # quiz_id -> {level, items, created}


def quiz(sid, level='cet4', count=10, use_llm_sentences=False):
    level = level if level in ('cet4', 'cet6') else 'cet4'
    count = max(5, min(30, int(count)))
    words = _pick_words(sid, level, count)
    items = []
    sentences = {}
    if use_llm_sentences and llm.available():
        sentences = _llm_sentences([w['word'] for w in words])
    for w in words:
        q = _make_choice(w, level)
        q['mode'] = 'choice'
        if w['word'] in sentences:
            q['mode'] = 'cloze'
            q['sentence'] = sentences[w['word']]
        items.append(q)
    qid = ('q%s' % time.time_ns())[-12:]
    QUIZ_CACHE[qid] = {'level': level, 'items': items, 'created': time.time()}
    # 清理过期缓存（>2小时）
    for k in [k for k, v in QUIZ_CACHE.items() if time.time() - v['created'] > 7200]:
        QUIZ_CACHE.pop(k, None)
    public = []
    for i, q in enumerate(items):
        public.append({k: v for k, v in q.items() if k != 'answer'} | {'qid': qid, 'index': i})
    return {'quiz_id': qid, 'level': level, 'count': len(items), 'questions': public}


def _llm_sentences(words):
    """用 LLM 为一批单词生成语境例句（目标词替换为 ____）。"""
    prompt = ('为下面每个英语单词写一个四六级难度、长度15-25词的英文例句，'
              '把例句中的该词替换成 ____（四个下划线）。输出 JSON：{"sentences": {"单词": "例句"}}\n单词：%s'
              % ', '.join(words))
    try:
        res = llm.chat_json([{'role': 'user', 'content': prompt}], temperature=0.4)
        return res.get('sentences', {}) if res else {}
    except llm.LLMError:
        return {}


def submit(sid, quiz_id, answers):
    """answers: {index: 所选key}。判分、更新生词本与词汇掌握度。"""
    data = QUIZ_CACHE.get(quiz_id)
    if not data:
        return {'error': '测验已过期，请重新开始'}
    results, right_n = [], 0
    prof = store.get_profile(sid)
    wb = prof.setdefault('wordbook', {})
    for i, q in enumerate(data['items']):
        chosen = (answers or {}).get(str(i)) or (answers or {}).get(i)
        ok = chosen == q['answer']
        right_n += ok
        rec = wb.setdefault(q['word'], {'level': data['level'], 'right': 0, 'wrong': 0,
                                        'meaning': q['options'][0]['meaning'], 'last': 0})
        rec['meaning'] = next((o['meaning'] for o in q['options'] if o['key'] == q['answer']), rec.get('meaning', ''))
        rec['right'] += 1 if ok else 0
        rec['wrong'] += 0 if ok else 1
        rec['last'] = time.time()
        if not ok:
            wrongbook.add(sid, 'vocab', q['word'], stem=(q.get('sentence') or '词义选择'),
                          your=str(chosen), answer=q['answer'] + ' ' + rec['meaning'],
                          subject='english', ref=quiz_id)
        results.append({'index': i, 'word': q['word'], 'answer': q['answer'],
                        'chosen': chosen, 'correct': ok, 'meaning': rec['meaning'],
                        'sentence': q.get('sentence', ''), 'phrase': q.get('phrase', '')})
    prof['stats']['quiz_done'] = prof.get('stats', {}).get('quiz_done', 0) + 1
    store.save_profile(sid, prof)
    score_pct = round(100 * right_n / max(1, len(data['items'])))
    store.update_mastery(sid, 'en_vocab_%s' % data['level'], 'english',
                         +4 if score_pct >= 80 else (+2 if score_pct >= 60 else -3),
                         wrong=score_pct < 60)
    store.log_event(sid, 'quiz', {'level': data['level'], 'right': right_n, 'total': len(data['items'])})
    awarded = points.notify(sid, 'quiz', {'right': right_n})
    return {'quiz_id': quiz_id, 'right': right_n, 'total': len(data['items']),
            'score_pct': score_pct, 'results': results, 'awarded': awarded}


def wordbook(sid, level=None):
    prof = store.get_profile(sid) or {}
    wb = prof.get('wordbook', {})
    out = sorted(wb.items(), key=lambda x: (-(x[1].get('wrong', 0)), x[0]))
    return [{'word': w, **info} for w, info in out if not level or info.get('level') == level]


def word_info(sid, word):
    """查词：先本地词库，失败时可选择 LLM 解释。"""
    word = (word or '').strip().lower()
    for level in ('cet4', 'cet6'):
        for w in _words(level):
            if w['word'] == word:
                return {'word': word, 'level': level, **w}
    if llm.available():
        try:
            res = llm.chat_json([{'role': 'user', 'content':
                '解释英语单词 "%s"：输出 JSON {"word","meaning":"中文释义","pos":"词性","example":"英文例句"}' % word}])
            if res:
                return res
        except llm.LLMError:
            pass
    return None
