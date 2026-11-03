# -*- coding: utf-8 -*-
"""HTTP 端到端测试：py -3 scripts/http_test.py [端口]"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _console import utf8  # noqa: E402
utf8()

PORT = sys.argv[1] if len(sys.argv) > 1 else '8765'
BASE = 'http://127.0.0.1:%s/api/' % PORT


def call(path, body=None, method=None):
    url = BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ('POST' if data else 'GET'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


boot = call('bootstrap')
print('[1] bootstrap ok, llm =', boot['llm'], ', subjects =', boot['subjects'])

sid = call('students', {'name': 'HTTP测试生'})['id']
print('[2] created student', sid)

r = call('qa', {'sid': sid, 'question': '帮我看看这道题：求行列式 |3A|，A是4阶，|A|=2', 'subject': 'linear_algebra', 'mode': 'guide'})
print('[3] qa ->', r['kp_name'], '| steps:', len(r['guidance']), '| offline:', r['offline'])

r = call('english/grade', {'sid': sid, 'kind': 'writing', 'level': 'cet4', 'prompt_id': 'w_c4_1',
                           'text': 'With the develop of society, more and more people begin to learn knowledges. There have many books in library. I very like reading.'})
print('[4] writing grade ->', r['score'], '| corrections:', len(r['corrections']), '| offline:', r['offline'])

r = call('vocab/quiz', {'sid': sid, 'level': 'cet4', 'count': 5})
answers = {str(i): q['options'][0]['key'] for i, q in enumerate(r['questions'])}
r2 = call('vocab/submit', {'sid': sid, 'quiz_id': r['quiz_id'], 'answers': answers})
print('[5] vocab ->', r2['right'], '/', r2['total'])

r = call('paper/generate', {'sid': sid, 'subject': 'linear_algebra', 'kp_ids': ['la_eq'], 'difficulty': 'easy'})
pid = r['id']
print('[6] paper generated ->', pid, len(r['questions']), 'questions, offline =', r['offline'])
paper = call('paper', {'sid': sid, 'id': pid}, 'GET') if False else call('paper?sid=%s&id=%s' % (sid, pid))
ans = {q['id']: ('A' if q['type'] == 'choice' else '答非所问的测试答案') for q in paper['questions']}
r2 = call('paper/submit', {'sid': sid, 'paper_id': pid, 'answers': ans})
print('[7] paper graded ->', r2['score'], '/', r2['total'], '| wrong kps:', r2['wrong_kps'])

r = call('notes/generate', {'sid': sid, 'subject': 'linear_algebra', 'kp_ids': ['la_rank'], 'include_materials': True})
print('[8] notes ->', r['title'][:40], '| md len:', len(r['markdown']))

r = call('materials', {'sid': sid, 'name': '测试资料', 'text': '线性方程组：非齐次通解等于特解加齐次通解，基础解系含 n-r 个向量。'})
print('[9] material added:', r['chunks'], 'chunks')

r = call('memory/preference', {'sid': sid, 'text': '答题先给直觉'})
call('feedback', {'sid': sid, 'module': 'qa', 'target': 'test', 'rating': 1, 'comment': '不错'})
r = call('memory/reflect', {'sid': sid})
print('[10] reflect ->', r['strategy'][:50].replace('\n', ' '))

r = call('dashboard?sid=' + sid)
print('[11] dashboard -> weak:', len(r['weak']), '| history:', len(r['history']))
print('\nHTTP 端到端全部通过 ✓')
