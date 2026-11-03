# -*- coding: utf-8 -*-
"""离线冒烟测试：不依赖大模型，验证全链路可用。运行：py -3 scripts/smoke_test.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _console import utf8  # noqa: E402

utf8()

from backend import english, knowledge, llm, materials, memory, notes, paper, qa, store, vocab  # noqa: E402

print('LLM available:', llm.available())


def step(name, fn):
    try:
        r = fn()
        print('[OK] %s' % name, ('-> %s' % json.dumps(r, ensure_ascii=False)[:120]) if r is not None else '')
        return r
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('[FAIL] %s: %s' % (name, e))
        sys.exit(1)


sid, _ = store.create_student('冒烟测试生')
print('student:', sid)

step('知识点匹配', lambda: [(s, k['name'], sc) for s, k, sc in knowledge.match_kps('求矩阵的特征值和特征向量')])
step('AI问答(离线)', lambda: qa.answer(sid, '老师，特征值怎么求？给我讲讲思路', subject='linear_algebra', mode='guide')['kp_name'])
step('英语作文批改(离线)', lambda: english.grade(sid, 'writing', 'With the develop of the society, more and more people begin to learn knowledges. I very like English. In my opinion, I think it is useful. There have many books. ', level='cet4', prompt_id='w_c4_1')['score'])
step('英语翻译批改(离线)', lambda: english.grade(sid, 'translation', 'The spring festival is the most important festival in China. People reunite with family and children get lucky money.', level='cet4', prompt_id='t_c4_2')['score'])
qz = step('词汇出题', lambda: vocab.quiz(sid, level='cet4', count=5))
answers = {str(i): q['options'][0]['key'] for i, q in enumerate(qz['questions'])}
step('词汇判分', lambda: vocab.submit(sid, qz['quiz_id'], answers)['right'])
step('生词本', lambda: len(vocab.wordbook(sid)))
pid = step('数学诊断卷(离线)', lambda: paper.generate(sid, 'linear_algebra', kp_ids=['la_eigen', 'la_det'], difficulty='mid')['id'])
paper_doc = store.get_paper(sid, pid)
ans = {q['id']: ('A' if q['type'] == 'choice' else '不会做') for q in paper_doc['questions']}
step('诊断卷判分', lambda: paper.submit(sid, pid, ans)['score'])
eid = step('英语诊断卷', lambda: paper.generate(sid, 'english', counts={'level': 'cet4', 'vocab': 4})['id'])
ep = store.get_paper(sid, eid)
eans = {q['id']: ('The Spring Festival is the most important traditional festival in China. People reunite with family and children receive lucky money.' if q['type'] in ('translation', 'writing') else 'A') for q in ep['questions']}
step('英语诊断卷判分', lambda: paper.submit(sid, eid, eans)['pct'])
step('讲义生成(离线)', lambda: notes.generate(sid, 'calculus', kp_ids=['ca_func'])['title'])
step('资料上传', lambda: materials.add_material(sid, '线代第三章讲义', '线性方程组的解的结构：非齐次通解=特解+齐次通解。基础解系含 n-r 个向量。 Ax=0 有非零解当且仅当 r(A)<n。'))
step('资料检索', lambda: [c['material'] for c in materials.retrieve(sid, '基础解系有几个向量')])
step('偏好指令', lambda: memory.add_preference(sid, '讲解时先给直觉再给证明'))
step('反馈记录', lambda: memory.add_feedback(sid, 'qa', '特征值', -1, '希望多给一道例题'))
step('自我反思(离线)', lambda: memory.reflect(sid)['strategy'][:60])
step('仪表盘', lambda: (store.get_student_summary(sid)['avg_by_subject'], len(knowledge.weak_kps(sid, top=5))))
print('\n全部通过 ✓')
