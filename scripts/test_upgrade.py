# -*- coding: utf-8 -*-
"""升级兼容性测试：装新版之后，老数据还在、老分数不跳变、新资源能进来。

用法：py -3 scripts/test_upgrade.py
覆盖：
  1. 老格式档案（mastery 只有 score，没有 bkt）→ 答对一次后分数不塌回 30
  2. 老档案答错一次后分数不异常跌到 0
  3. 老错题本 / 积分 / 讲义 / 历史记录在"换版"后仍可读
  4. 静态资源同步：数据目录里缺文件/旧文件 → 被新版资源补齐
  5. 数据库目录（db/）不被资源同步动到
"""
import json
import os
import shutil
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

fails = []


def check(cond, msg):
    print('[%s] %s' % ('OK' if cond else 'FAIL', msg))
    if not cond:
        fails.append(msg)


# ---------------- 1~3：老数据 → 新版本 ----------------
tmp = tempfile.mkdtemp(prefix='zy_up_')
data_dir = os.path.join(tmp, 'data')
os.makedirs(os.path.join(data_dir, 'db'), exist_ok=True)
for sub in ('vocab', 'knowledge', 'bank', 'rubrics'):
    src = os.path.join(ROOT, 'data', sub)
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(data_dir, sub))
os.environ['ZY_DATA_DIR'] = data_dir
os.environ['ZY_CONFIG'] = os.path.join(tmp, 'config.json')

from backend import points, store, wrongbook  # noqa: E402

sid, _ = store.create_student('老用户')
# 手工把档案改造成"旧版本格式"：mastery 里没有 bkt 字段
prof = store.get_profile(sid)
prof['mastery'] = {
    'la_det': {'score': 68, 'hits': 5, 'wrong': 1, 'last': 1700000000, 'subject': 'linear_algebra'},
    'la_eigen': {'score': 42, 'hits': 3, 'wrong': 2, 'last': 1700000000, 'subject': 'linear_algebra'},
}
prof['stats'] = {'qa': 12, 'graded': 3, 'quiz_done': 2, 'papers_done': 1, 'notes': 2}
store.save_profile(sid, prof)

# 老错题 & 积分也要在
iid = wrongbook.add(sid, 'math', '行列式', stem='|1 2; 3 4|', your='-1', answer='-2',
                    note='对角线相减', subject='linear_algebra', kp_id='la_det')
st = points.load(sid)
st.setdefault('earn', []).append({'pts': 88, 'title': '老账本', 'cat': 'old', 'ts': 1700000000})
st.setdefault('spent', [])
points.save(sid, st)

before = store.get_profile(sid)['mastery']['la_det']['score']
rec = store.observe_answer(sid, 'la_det', 'linear_algebra', True)
after = rec['score']
check(after >= before - 2,
      '老分数 68 答对一次后不塌回默认值（%d → %d）' % (before, after))
check(rec.get('bkt') and rec['bkt'].get('n', 0) >= 6,
      '迁移时继承历史作答次数（n=%s，原 hits=5）' % (rec.get('bkt') or {}).get('n'))

low = store.observe_answer(sid, 'la_eigen', 'linear_algebra', False)
check(low['score'] > 5, '老分数 42 答错一次后不会直接掉到 0（→ %d）' % low['score'])

# 老数据仍可读
wb = wrongbook._load(sid) or {}
check(any(x['id'] == iid for x in (wb.get('items') or [])), '老错题本条目还在')
check(int(points.balance(points.load(sid))) == 88, '老积分余额还在（88）')
check((store.get_profile(sid).get('stats') or {}).get('qa') == 12, '老统计还在（qa=12）')

# ---------------- 4~5：静态资源同步 ----------------
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    'zy_run_exe', os.path.join(ROOT, 'packaging', 'run_exe.py'))
_run_exe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run_exe)
_seed_assets = _run_exe._seed_assets

# 模拟"老用户的数据目录"：删掉一个资源文件、改坏一个、并在 db 里放一个标记文件
kg_dir = os.path.join(data_dir, 'knowledge')
vocab_dir = os.path.join(data_dir, 'vocab')
kg_files = sorted(os.listdir(kg_dir)) if os.path.isdir(kg_dir) else []
if kg_files:
    os.remove(os.path.join(kg_dir, kg_files[0]))
vocab_files = sorted(os.listdir(vocab_dir)) if os.path.isdir(vocab_dir) else []
if vocab_files:
    with open(os.path.join(vocab_dir, vocab_files[0]), 'w', encoding='utf-8') as f:
        f.write('{"broken": true}')      # 大小不同 → 应被新版覆盖
marker = os.path.join(data_dir, 'db', '.keep_me')
with open(marker, 'w', encoding='utf-8') as f:
    f.write('user data')

_seed_assets(data_dir, ROOT)

if kg_files:
    check(os.path.exists(os.path.join(kg_dir, kg_files[0])), '被删掉的知识图谱文件已由新版补齐')
if vocab_files:
    size_now = os.path.getsize(os.path.join(vocab_dir, vocab_files[0]))
    size_src = os.path.getsize(os.path.join(ROOT, 'data', 'vocab', vocab_files[0]))
    check(size_now == size_src, '被改坏的词库文件已被新版覆盖')
check(os.path.exists(marker), 'db/ 下的用户数据没被资源同步动到')

print()
if fails:
    print('%d 项失败' % len(fails))
    sys.exit(1)
print('全部通过 ✓')
