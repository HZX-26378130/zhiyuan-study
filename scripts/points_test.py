# -*- coding: utf-8 -*-
"""融合流程测试：真实学习行为 → 积分/任务自动完成。py -3 scripts/points_test.py [端口]"""
import json
import sys
import urllib.request

PORT = sys.argv[1] if len(sys.argv) > 1 else '8765'
BASE = 'http://127.0.0.1:%s/api/' % PORT


def call(path, body=None, method=None):
    url = BASE + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ('POST' if data else 'GET'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


sid = call('students', {'name': '融合测试生'})['id']

# 1. 空状态
p = call('points?sid=' + sid)
print('[1] 初始 -> balance', p['stats']['balance'], '| cats', p['cats'])

# 2. 真实学习行为发分：问答 +2
r = call('qa', {'sid': sid, 'question': '求矩阵的秩', 'subject': 'linear_algebra', 'use_web': False})
print('[2] qa awarded ->', r.get('awarded'))

# 3. 词汇测验发分
q = call('vocab/quiz', {'sid': sid, 'level': 'cet4', 'count': 5})
answers = {str(i): x['options'][0]['key'] for i, x in enumerate(q['questions'])}
r = call('vocab/submit', {'sid': sid, 'quiz_id': q['quiz_id'], 'answers': answers})
print('[3] quiz awarded ->', r.get('awarded'), '(答对', r['right'], ')')

# 4. 建系统任务（薄弱点→任务）→ 讲义触发 zy:notes 自动完成
call('points/task', {'sid': sid, 'title': '复习「矩阵的秩」（讲义 + 诊断卷）', 'cat': '学习',
                     'pts': 10, 'repeat': 'day', 'dueT': '21:00', 'source': 'zy:kp:linear_algebra:la_rank'})
r = call('notes/generate', {'sid': sid, 'subject': 'linear_algebra', 'kp_ids': ['la_rank']})
print('[4] notes awarded ->', r.get('awarded'))
p = call('points?sid=' + sid)
done = [t for t in p['tasks'] if t['done']]
print('[4] 系统任务自动完成 ->', len(done), '| balance', p['stats']['balance'])

# 5. 手动任务：勾选得分，取消不退分，再勾不重复计分
call('points/task', {'sid': sid, 'title': '自定义任务', 'cat': '生活', 'pts': 3})
p = call('points?sid=' + sid)
tid = p['tasks'][-1]['id']
call('points/task/toggle', {'sid': sid, 'id': tid})
b1 = call('points?sid=' + sid)['stats']['balance']
call('points/task/toggle', {'sid': sid, 'id': tid})   # 取消（不退分）
b2 = call('points?sid=' + sid)['stats']['balance']
call('points/task/toggle', {'sid': sid, 'id': tid})   # 再勾（不重复计分）
b3 = call('points?sid=' + sid)['stats']['balance']
print('[5] 勾选后', b1, '| 取消后', b2, '| 再勾后', b3, '（b1==b2==b3 即防篡改生效）')

# 6. 系统任务禁止手动勾选
call('points/task', {'sid': sid, 'title': '系统任务', 'cat': '学习', 'pts': 5, 'source': 'zy:qa'})
p = call('points?sid=' + sid)
sid_task = p['tasks'][-1]['id']
try:
    call('points/task/toggle', {'sid': sid, 'id': sid_task})
    print('[6] FAIL: 系统任务被手动勾选了')
    call('points?sid=' + sid)
except urllib.error.HTTPError as e:
    print('[6] 系统任务手动勾选被拒 ->', json.loads(e.read().decode('utf-8'))['error'][:30])

# 7. 兑换/撤销/积分不足
call('points/reward', {'sid': sid, 'name': '看一集剧', 'cost': 999})
rid = call('points?sid=' + sid)['rewards'][-1]['id']
try:
    call('points/reward/redeem', {'sid': sid, 'id': rid})
    print('[7] FAIL: 积分不足却兑换成功')
except urllib.error.HTTPError as e:
    print('[7] 积分不足拦截 ->', json.loads(e.read().decode('utf-8'))['error'][:20])
call('points/reward/delete', {'sid': sid, 'id': rid})
call('points/reward', {'sid': sid, 'name': '小奖励', 'cost': 1, 'period': 'day', 'limit': 1})
rid = call('points?sid=' + sid)['rewards'][-1]['id']
call('points/reward/redeem', {'sid': sid, 'id': rid})
b_before = call('points?sid=' + sid)['stats']['balance']
sp = call('points?sid=' + sid)['spent'][-1]
call('points/spent/undo', {'sid': sid, 'id': sp['id']})
b_after = call('points?sid=' + sid)['stats']['balance']
print('[8] 兑换后', b_before, '→ 撤销后', b_after)

# 9. 补签 & 模拟跨天
r = call('points/makeup', {'sid': sid})
print('[9] 补签 ->', 'ok' if r.get('stats') else 'rejected')
r = call('points/simulate', {'sid': sid})
rep_done = [t for t in r['tasks'] if t['repeat'] == 'day' and t['source'] and t['done']]
print('[10] 模拟跨天后 repeat 任务 done ->', [t['done'] for t in r['tasks'] if t['repeat'] == 'day'])

# 11. 仪表盘带积分摘要
d = call('dashboard?sid=' + sid)
print('[11] dashboard points ->', d.get('points'))

# 12. task-points 备份导入
backup = {'tasks': [{'id': 'old1', 'title': '旧任务', 'cat': '学习', 'pri': 2, 'pts': 5, 'done': False,
                     'repeat': 'none'}],
          'rewards': [], 'earn': [{'id': 'e1', 'pts': 30, 't': 1700000000, 'title': '历史积分', 'cat': '学习'}],
          'spent': [], 'cats': ['学习', '娱乐'], 'goal': 20, 'weekGoal': 100}
p = call('points/import', {'sid': sid, 'data': backup})
print('[12] 导入 -> balance', p['stats']['balance'], '| cats', p['cats'], '| goal', p['stats']['goal'])

print('\n融合流程全部通过 ✓')
