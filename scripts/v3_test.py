# -*- coding: utf-8 -*-
"""v3 测试：新学科问答/出卷 + 错题本 + 文档上传批改。py -3 scripts/v3_test.py"""
import json
import os
import shutil
import urllib.error
import urllib.request

B = 'http://127.0.0.1:8765/api/'


def call(p, b=None, m=None):
    d = json.dumps(b).encode() if b is not None else None
    rq = urllib.request.Request(B + p, data=d, method=m or ('POST' if d else 'GET'),
                                headers={'Content-Type': 'application/json'})
    try:
        return json.load(urllib.request.urlopen(rq, timeout=60))
    except urllib.error.HTTPError as e:
        return {'_err': json.loads(e.read().decode())['error']}


sid = call('students', {'name': 'v3测试生'})['id']

r = call('qa', {'sid': sid, 'question': 'malloc 和 free 怎么用？指针什么时候会变成野指针？', 'use_web': False})
print('[1] C语言问答 ->', r['kp_name'], '| awarded', r.get('awarded'))
r = call('qa', {'sid': sid, 'question': '光合作用的暗反应 C3 C5 含量怎么变', 'subject': 'biology', 'use_web': False})
print('[2] 生物问答 ->', r['kp_name'])
r = call('qa', {'sid': sid, 'question': 'pH计算和盐类水解', 'subject': 'chemistry', 'use_web': False})
print('[3] 化学问答 ->', r['kp_name'])

r = call('paper/generate', {'sid': sid, 'subject': 'c_lang', 'kp_ids': ['c_pointer', 'c_array']})
pid = r['id']
print('[4] C语言诊断卷 ->', len(r['questions']), '题')
pp = call('paper?sid=%s&id=%s' % (sid, pid))
ans = {q['id']: '乱答' for q in pp['questions']}
r = call('paper/submit', {'sid': sid, 'paper_id': pid, 'answers': ans})
print('[5] 交卷 -> score', r['score'], '| awarded', r.get('awarded'))

wb = call('wrongbook?sid=' + sid)
print('[6] 错题本 ->', wb['total'], '条 | 分类:', wb['byCategory'][:3])
iid = wb['items'][0]['id']
r = call('wrongbook/resolve', {'sid': sid, 'id': iid, 'force': True})
print('[7] 标记掌握 -> 剩余', r['total'])
call('wrongbook/resolve', {'sid': sid, 'id': iid, 'resolved': False, 'force': True})

boundary = 'b' * 20
doc = ('In the age of AI, more and more people begin to use AI. There have many benefits. '
       'I very like it. As we all knows, study need thinking.')
body = (('----%s\r\nContent-Disposition: form-data; name="sid"\r\n\r\n%s\r\n'
         '----%s\r\nContent-Disposition: form-data; name="file"; filename="essay.txt"\r\n'
         'Content-Type: text/plain\r\n\r\n%s\r\n----%s----\r\n' % (boundary, sid, boundary, doc, boundary))).encode()
rq = urllib.request.Request(B + 'upload/extract', data=body, method='POST',
                            headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
up = json.load(urllib.request.urlopen(rq, timeout=30))
print('[8] 文档抽取 ->', up['kind'], up['name'], len(up['text']), '字')
r = call('english/grade', {'sid': sid, 'kind': 'writing', 'level': 'cet4', 'text': up['text']})
print('[9] 批改 -> score', r['score'], '| corrections', len(r['corrections']), '| awarded', r.get('awarded'))
wb = call('wrongbook?sid=' + sid)
print('[10] 错题本分类统计 ->', wb['byKind'])

idx = json.load(open(r'data/db/students.json', encoding='utf-8'))
keep = {k: v for k, v in idx.items() if v.get('name') == '我的档案'}
for k in idx:
    if k not in keep:
        shutil.rmtree(os.path.join('data', 'db', k), ignore_errors=True)
json.dump(keep, open(r'data/db/students.json', 'w', encoding='utf-8'), ensure_ascii=False)
print('cleaned ✓')
