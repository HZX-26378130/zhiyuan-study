# -*- coding: utf-8 -*-
"""llm._extract_json 回归测试：模型输出被截断 / 带非法 LaTeX 转义时仍能解析。

用法：py -3 scripts/test_llm_json.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

from backend import llm  # noqa: E402

CASES = [
    # (模型原始输出, 期望断言说明, 校验函数)
    ('{"a": 1}', '原本合法的 JSON 原样解析', lambda r: r == {'a': 1}),
    ('```json\n{"a": 1}\n```', '带代码围栏', lambda r: r == {'a': 1}),
    ('好的，结果如下：{"a": 1} 希望能帮到你', '前后有说明文字', lambda r: r == {'a': 1}),
    ('{"e":"$$\\det A=\\sum_{i=1}^n a_i$$"}', '已正确转义的 LaTeX（幂等）',
     lambda r: '\\det' in r['e'] and '\\sum' in r['e']),
    ('{"e":"$$\\det A$$"}', '未转义 LaTeX：\\det（\\d 本非法）',
     lambda r: '\\det' in r['e']),
    ('{"e":"$3\\times3$"}', '未转义 LaTeX：\\times 不能被当成制表符',
     lambda r: '\\times' in r['e'] and '\t' not in r['e']),
    ('{"e":"$\\begin{pmatrix}$"}', '未转义 LaTeX：\\begin 不能被当成退格',
     lambda r: '\\begin' in r['e'] and '\b' not in r['e']),
    ('{"e":"$\\nabla f$"}', '未转义 LaTeX：\\nabla',
     lambda r: '\\nabla' in r['e']),
    ('{"a":1,"b":[1,2', '截断：缺括号', lambda r: r == {'a': 1, 'b': [1, 2]}),
    ('{"a":1,"b":"未闭合', '截断：字符串未闭合', lambda r: r == {'a': 1, 'b': '未闭合'}),
    ('{"a":1,"b":[1,2],"c":"x","d":"截断在字段中间', '截断：尾部残缺字段被裁掉',
     lambda r: r['a'] == 1 and r['c'] == 'x'),
    ('{"kp_name":"行列式","guidance":["g1","g2"],"explanation":"讲', '截断 + 中文字段',
     lambda r: r['kp_name'] == '行列式' and r['guidance'] == ['g1', 'g2']),
    ('{"e":"第一行\\n第二行","n":1}', '正常换行转义保持为换行',
     lambda r: '\n' in r['e']),
    ('不是 JSON 的普通文字', '完全没有 JSON → None', lambda r: r is None),
    ('{"a": ', '损坏到无法挽救 → 不死循环', lambda r: r is None or isinstance(r, dict)),
]

fails = 0
for raw, note, check in CASES:
    try:
        got = llm._extract_json(raw)
        ok = bool(check(got))
    except Exception as e:  # noqa: BLE001
        got, ok = 'EXC %r' % e, False
    print('[%s] %-32s -> %s' % ('OK' if ok else 'FAIL', note,
                                json.dumps(got, ensure_ascii=False)[:110]))
    if not ok:
        fails += 1

print('\n%d/%d 通过' % (len(CASES) - fails, len(CASES)))
sys.exit(1 if fails else 0)
