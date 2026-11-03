# -*- coding: utf-8 -*-
"""知识来源与联网检索：
1) 权威来源直达链接（知网/百度学术/智慧教育平台/MOOC/MIT OCW）；
2) 真实联网搜索：默认免 Key 的 Bing HTML 版（国内可直连），也可配置博查 API；
3) 开源题库/高校资料索引（data/bank/sources.json）检索。"""
import json
import os
import re
import urllib.parse
import urllib.request

from . import llm, store

_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
       'Accept-Language': 'zh-CN,zh;q=0.9'}


def source_links(kp_name, subject=''):
    kw = urllib.parse.quote(kp_name)
    links = [
        {'title': '中国知网（CNKI）文献检索：%s' % kp_name,
         'url': 'https://kns.cnki.net/kns8s/defaultresult/index?kw=%s' % kw},
        {'title': '百度学术：%s' % kp_name,
         'url': 'https://xueshu.baidu.com/s?wd=%s' % kw},
        {'title': '国家高等教育智慧教育平台',
         'url': 'https://www.smartedu.cn/'},
        {'title': '中国大学MOOC：%s 相关课程' % kp_name,
         'url': 'https://www.icourse163.org/search.htm?search=%s' % kw},
    ]
    if subject == 'linear_algebra':
        links.append({'title': 'MIT 18.06 Linear Algebra (Gilbert Strang)',
                      'url': 'https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/'})
    elif subject == 'calculus':
        links.append({'title': 'MIT 18.01/18.02 单变量/多变量微积分',
                      'url': 'https://ocw.mit.edu/courses/18-01-single-variable-calculus-fall-2006/'})
    return links


# ---------------- 免 Key 真实联网搜索 ----------------

def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


def _strip_tags(html):
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', '', html)
    return re.sub(r'\s+', ' ', text).strip()


def _bing(query, count):
    html = _fetch('https://www.bing.com/search?q=%s&setlang=zh-hans&count=%d'
                  % (urllib.parse.quote(query), max(10, count)))
    out = []
    for m in re.finditer(r'<li class="b_algo".*?<h2>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<p[^>]*>(.*?)</p>)?</li>',
                         html, re.S):
        url, title, snippet = m.group(1), _strip_tags(m.group(2)), _strip_tags(m.group(3) or '')
        if url.startswith('http'):
            out.append({'title': title, 'url': url, 'snippet': snippet[:320]})
        if len(out) >= count:
            break
    return out


def _ddg(query, count):
    html = _fetch('https://html.duckduckgo.com/html/?q=%s' % urllib.parse.quote(query))
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         html, re.S):
        url, title, snippet = m.group(1), _strip_tags(m.group(2)), _strip_tags(m.group(3))
        if 'uddg=' in url:
            url = urllib.parse.unquote(url.split('uddg=')[1].split('&')[0])
        out.append({'title': title, 'url': url, 'snippet': snippet[:320]})
        if len(out) >= count:
            break
    return out


def _bocha(query, count):
    cfg = llm.load_config().get('search', {})
    body = json.dumps({'query': query, 'count': count, 'summary': True}).encode('utf-8')
    req = urllib.request.Request('https://api.bochaai.com/v1/web-search', data=body, method='POST', headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg['api_key']})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    pages = data.get('data', {}).get('webPages', {}).get('value', [])
    return [{'title': p.get('name'), 'url': p.get('url'), 'snippet': (p.get('summary') or p.get('snippet', ''))[:300]}
            for p in pages[:count]]


def web_search(query, count=5):
    """真实联网搜索：优先博查（已配置时），否则免 Key 的 Bing（国内可直连），再兜底 DDG。"""
    cfg = llm.load_config().get('search', {})
    providers = []
    if cfg.get('api_key') and cfg.get('provider', 'bocha') == 'bocha':
        providers.append(('博查', _bocha))
    providers += [('Bing', _bing), ('DuckDuckGo', _ddg)]
    for name, fn in providers:
        try:
            results = fn(query, count)
            if results:
                return results
        except (OSError, ValueError, KeyError):
            continue
    return []


# ---------------- 开源题库 / 高校资料索引 ----------------

def _sources_index():
    path = os.path.join(store.DATA_DIR, 'bank', 'sources.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f).get('sources', [])
    except (OSError, ValueError):
        return []


def match_sources(query, top=4):
    """在高校资料/开源题库索引中检索（关键词+二元组）。"""
    q = query.lower()
    grams = set(q[i:i + 2] for i in range(len(q) - 1)) or {q}
    scored = []
    for s in _sources_index():
        text = (s.get('name', '') + ' ' + ' '.join(s.get('tags', [])) + ' ' + s.get('note', '')).lower()
        score = sum(2 for kw in s.get('tags', []) if kw.lower() in q)
        tg = set(text[i:i + 2] for i in range(len(text) - 1))
        score += len(grams & tg) * 0.1
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:top]]


def all_sources():
    return _sources_index()
