# -*- coding: utf-8 -*-
"""BKT 知识追踪回归测试（纯离线，不碰网络）。

用法：py -3 scripts/test_kt.py
覆盖：
  1. 概率模型的数学性质（答对上调/答错下调、边界夹紧、蒙对/手滑修正）
  2. store.observe_answer 写入 profile：score 与 bkt 状态同步、错题计数正确
  3. 连续答对收敛到高掌握度；连续答错收敛到低掌握度
  4. 变式重练（wrongbook.submit_practice）也会更新掌握度
  5. 旧接口 update_mastery 仍可用（问答这类无对错信号继续走它）
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _console import utf8
    utf8()
except Exception:  # noqa: BLE001
    pass

# 隔离数据目录，避免污染真实数据。
# 注意：知识图谱/词库等静态资源也要带过去，否则 knowledge 模块会找不到 data/knowledge
import shutil
_tmp = tempfile.mkdtemp(prefix='zy_kt_')
for _sub in ('vocab', 'knowledge', 'bank', 'rubrics'):
    _src = os.path.join(ROOT, 'data', _sub)
    if os.path.isdir(_src):
        shutil.copytree(_src, os.path.join(_tmp, 'data', _sub))
os.environ['ZY_DATA_DIR'] = os.path.join(_tmp, 'data')

from backend import kt, store  # noqa: E402

fails = []


def check(cond, msg):
    print('[%s] %s' % ('OK' if cond else 'FAIL', msg))
    if not cond:
        fails.append(msg)


# ---------- 1. 数学性质 ----------
st0 = kt.new_state('linear_algebra')
p0 = st0['p']
st1 = kt.observe(st0, True)
check(st1['p'] > p0, '答对后 p 上升（%.3f -> %.3f）' % (p0, st1['p']))
st2 = kt.observe(st0, False)
check(st2['p'] < p0, '答错后 p 下降（%.3f -> %.3f）' % (p0, st2['p']))
check(0 < st1['p'] < 1 and 0 < st2['p'] < 1, '概率始终落在 (0,1) 区间')

# 蒙对修正：初始掌握度 0.3 时，答对的涨幅应小于"假定必对"的情形
big = kt.observe({'p': 0.9}, True)['p']
small = kt.observe({'p': 0.1}, True)['p']
check((big - 0.9) < (small - 0.1) + 1e-9, '已掌握者答对的增益小于未掌握者（蒙对已折价）')

# 收敛性
h = kt.new_state()
for _ in range(8):
    h = kt.observe(h, True)
check(kt.score(h) >= 90, '连续答对 8 次 → 掌握度 %d（≥90）' % kt.score(h))
lo = kt.new_state()
for _ in range(8):
    lo = kt.observe(lo, False)
check(kt.score(lo) <= 20, '连续答错 8 次 → 掌握度 %d（≤20，含学习转移的下限）' % kt.score(lo))

# 参数可覆盖
prm = dict(kt.DEFAULT_PARAMS, p_learn=0.4)
fast = kt.observe({'p': 0.3}, True, prm)['p']
slow = kt.observe({'p': 0.3}, True)['p']
check(fast > slow, '提高 p_learn 后同样答对涨得更快（%.3f > %.3f）' % (fast, slow))

# ---------- 2. store.observe_answer ----------
sid, _ = store.create_student('KT 测试生')
rec = store.observe_answer(sid, 'la_det', 'linear_algebra', True)
check(rec and rec.get('bkt') and rec.get('score') is not None, 'observe_answer 写入 bkt 状态与 score')
first_score = rec['score']
rec2 = store.observe_answer(sid, 'la_det', 'linear_algebra', True)
check(rec2['score'] > first_score, '再答对一次 score 继续上升（%d -> %d）' % (first_score, rec2['score']))
check(rec2['wrong'] == 0 and rec2['hits'] == 2, '答对不增加错题计数，hits=2')
rec3 = store.observe_answer(sid, 'la_det', 'linear_algebra', False)
check(rec3['score'] < rec2['score'] and rec3['wrong'] == 1, '答错后降分且 wrong=1')

# 持久化检查
prof = store.get_profile(sid) or {}
check('la_det' in (prof.get('mastery') or {}), '掌握度已持久化到 profile')

# ---------- 3. 旧接口仍可用 ----------
rec4 = store.update_mastery(sid, 'la_matrix', 'linear_algebra', 2)
check(rec4 and rec4['score'] is not None, '旧接口 update_mastery 仍可用（问答弱信号）')

# ---------- 4. 变式重练接入 ----------
try:
    from backend import wrongbook
    iid = wrongbook.add(sid, 'math', '行列式', stem='计算 |1 2; 3 4|', your='-1',
                        answer='-2', note='对角线相减', subject='linear_algebra', kp_id='la_det')
    before = (store.get_profile(sid) or {}).get('mastery', {}).get('la_det', {}).get('score')
    wrongbook.generate_variants(sid, iid)      # 离线时退回图谱例题
    vs = (wrongbook._load(sid) or {}).get('items', [])
    target = next((x for x in vs if x['id'] == iid), None)
    if target and target.get('variants'):
        wrongbook.submit_practice(sid, iid, 0, target['variants'][0].get('answer', ''), self_correct=True)
        after = (store.get_profile(sid) or {}).get('mastery', {}).get('la_det', {}).get('score')
        check(after != before, '变式重练也更新掌握度（%s -> %s）' % (before, after))
    else:
        check(True, '变式题为空（离线且无图谱例题），跳过重练校验')
except Exception as e:  # noqa: BLE001
    check(False, '变式重练链路异常: %r' % (e,))

print()
if fails:
    print('%d 项失败' % len(fails))
    sys.exit(1)
print('全部通过 ✓')
