# -*- coding: utf-8 -*-
"""v2 新端点测试：py -3 scripts/http_test_v2.py [端口]"""
import json
import os
import struct
import sys
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _console import utf8  # noqa: E402
utf8()

PORT = sys.argv[1] if len(sys.argv) > 1 else '8765'
BASE = 'http://127.0.0.1:%s/api/' % PORT


def call(path, body=None, method=None, expect_error=False):
    url = BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ('POST' if data else 'GET'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if expect_error and 400 <= e.code < 500:
            return json.loads(e.read().decode('utf-8'))
        raise


sid = call('students', {'name': 'V2测试生'})['id']

# 1. 配置读取（脱敏）
c = call('config')
print('[1] config ->', c['llm']['base_url'], '| has_key:', c['llm']['has_key'], '| vision:', c['llm']['vision_model'])

# 2. 配置测试连接（无Key → ok:False 且信息可读）
t = call('config/test', {})
print('[2] config/test (无Key) -> ok:', t['ok'], '| err:', t.get('error', '')[:40])

# 3. 图片上传 + 访问（生成1x1 PNG）
png = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63fccf00' '0000040001' 'b7f5d1a30000000049454e44ae426082')
boundary = uuid.uuid4().hex
body = ('--%s\r\nContent-Disposition: form-data; name="sid"\r\n\r\n%s\r\n'
        '--%s\r\nContent-Disposition: form-data; name="file"; filename="test.png"\r\n'
        'Content-Type: image/png\r\n\r\n' % (boundary, sid, boundary)).encode() + png + ('\r\n--%s--\r\n' % boundary).encode()
req = urllib.request.Request(BASE + 'upload/image', data=body, method='POST',
                             headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
up = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8'))['results'][0]
print('[3] upload image ->', up['file'])
img = urllib.request.urlopen('http://127.0.0.1:%s%s' % (PORT, up['url']), timeout=15)
print('[4] serve image ->', img.headers['Content-Type'], len(img.read()), 'bytes')

# 5. 带图片的问答（无vision → 提示；带文字则正常）
r = call('qa', {'sid': sid, 'question': '', 'image': up['file']}, expect_error=True)
print('[5] qa image-only (no vision) ->', r.get('error'), '|', r.get('message', '')[:40])
r = call('qa', {'sid': sid, 'question': '证明：单调有界数列必收敛', 'image': up['file'], 'subject': 'calculus', 'use_web': False})
print('[6] qa with image+text -> kp:', r['kp_name'], '| counter:', len(r.get('counter_questions', [])))

# 7. 出卷+交卷 → 报告
r = call('paper/generate', {'sid': sid, 'subject': 'linear_algebra', 'kp_ids': ['la_eigen']})
pid = r['id']
paper = call('paper?sid=%s&id=%s' % (sid, pid))
ans = {q['id']: '随便答错' for q in paper['questions']}
call('paper/submit', {'sid': sid, 'paper_id': pid, 'answers': ans})
paper = call('paper?sid=%s&id=%s' % (sid, pid))
print('[7] report ->', len(paper.get('report', [])), 'entries | first kp:', paper['report'][0]['kp_name'] if paper['report'] else '-',
      '| similar:', len(paper['report'][0].get('similar', [])) if paper['report'] else 0)

# 8. 反馈编辑/删除/策略卡手动编辑
call('feedback', {'sid': sid, 'module': 'qa', 'target': 'x', 'rating': -1, 'comment': '原话'})
mem = call('memory?sid=' + sid)
ts = mem['feedback'][0]['ts']
mem = call('memory/feedback/update', {'sid': sid, 'ts': ts, 'rating': 1, 'comment': '改好了'})
fb = [f for f in mem['feedback'] if abs(f['ts'] - ts) < 0.001][0]
print('[8] feedback update ->', fb['rating'], fb['comment'], '| edited:', fb.get('edited'))
mem = call('memory/feedback/delete', {'sid': sid, 'ts': ts})
print('[9] feedback delete ->', len(mem['feedback']), 'left')
mem = call('memory/strategy', {'sid': sid, 'text': '手动策略：多给反例'})
print('[10] strategy manual ->', mem['strategy'][:20])

# 11. 真题列表
b = call('bootstrap')
years = [p.get('year') for p in b['writing_prompts'] if p.get('year')]
tyears = [t.get('year') for t in b['translation_items'] if t.get('year')]
print('[11] bank -> writing years:', years, '| translation years:', tyears)

# 12. 资料索引
s = call('sources')
print('[12] sources ->', len(s['sources']), '个来源 |', s['sources'][0]['name'][:30])

print('\nv2 端点全部通过 ✓')
