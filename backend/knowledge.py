# -*- coding: utf-8 -*-
"""知识图谱：加载线代/数分知识点，关键词匹配定位知识点，维护学生薄弱点画像。"""
import json
import os
import time

from . import store

BASE = store.BASE
KG_DIR = os.path.join(store.DATA_DIR, 'knowledge')

SUBJECTS = {}  # subject -> {name, kps: {id: kp}}


def _load_subjects():
    if SUBJECTS:
        return
    for fn in os.listdir(KG_DIR):
        if not fn.endswith('.json'):
            continue
        with open(os.path.join(KG_DIR, fn), encoding='utf-8') as f:
            data = json.load(f)
        SUBJECTS[data['subject']] = {
            'name': data['name'],
            'kps': {kp['id']: kp for kp in data['kps']},
        }


def subjects():
    _load_subjects()
    return {s: v['name'] for s, v in SUBJECTS.items()}


def get_subject(subject):
    _load_subjects()
    return SUBJECTS.get(subject)


def get_kp(subject, kp_id):
    sub = get_subject(subject)
    return sub['kps'].get(kp_id) if sub else None


def kp_tree(subject):
    sub = get_subject(subject)
    if not sub:
        return []
    return sorted(sub['kps'].values(), key=lambda k: k['id'])


def _bigrams(text):
    t = ''.join(c for c in text.lower() if c.isalnum())
    return set(t[i:i + 2] for i in range(len(t) - 1)) or {t}


# 数学符号/口语化表述 → 知识点 的附加匹配规则（解决整段题目只有符号时的定位问题）
SYMBOL_RULES = {
    'linear_algebra': [
        ('λ', 'la_eigen'), ('特征', 'la_eigen'), ('可逆', 'la_inverse'), ('伴随', 'la_inverse'),
        ('秩', 'la_rank'), ('行列式', 'la_det'), ('|A|', 'la_det'), ('对角化', 'la_diag'),
        ('相似', 'la_diag'), ('正定', 'la_quad'), ('二次型', 'la_quad'), ('合同', 'la_quad'),
        ('方程组', 'la_eq'), ('基础解系', 'la_eq'), ('通解', 'la_eq'), ('极大无关', 'la_vector'),
        ('线性相关', 'la_vector'), ('线性无关', 'la_vector'), ('正交化', 'la_space'),
        ('过渡矩阵', 'la_space'), ('基变换', 'la_space'), ('转置', 'la_matrix'), ('初等变换', 'la_matrix'),
    ],
    'calculus': [
        ('∫', 'ca_int_def'), ('积分', 'ca_int_def'), ('lim', 'ca_seq'), ('极限', 'ca_func'),
        ('级数', 'ca_series_num'), ('Σ', 'ca_series_num'), ('收敛', 'ca_series_num'),
        ('幂级数', 'ca_series_pow'), ('展开', 'ca_series_pow'), ('洛必达', 'ca_mvt'),
        ('泰勒', 'ca_mvt'), ('中值', 'ca_mvt'), ('连续', 'ca_func'), ('间断', 'ca_func'),
        ('导数', 'ca_deriv'), ('微分', 'ca_deriv'), ('可导', 'ca_deriv'), ('偏导', 'ca_multi'),
        ('全微分', 'ca_multi'), ('极值', 'ca_multi'), ('二重', 'ca_multi_int'),
        ('极坐标', 'ca_multi_int'), ('微分方程', 'ca_ode'), ('通项', 'ca_series_num'),
    ],
    'c_lang': [
        ('指针', 'c_pointer'), ('野指针', 'c_pointer'), ('解引用', 'c_pointer'), ('地址', 'c_pointer'),
        ('printf', 'c_data'), ('scanf', 'c_data'), ('类型转换', 'c_data'), ('整除', 'c_data'), ('自增', 'c_data'),
        ('循环', 'c_flow'), ('switch', 'c_flow'), ('分支', 'c_flow'), ('break', 'c_flow'), ('continue', 'c_flow'),
        ('递归', 'c_func'), ('函数', 'c_func'), ('传值', 'c_func'), ('形参', 'c_func'),
        ('数组', 'c_array'), ('字符串', 'c_array'), ('strlen', 'c_array'), ('越界', 'c_array'),
        ('结构体', 'c_struct'), ('typedef', 'c_struct'), ('链表', 'c_struct'),
        ('malloc', 'c_mem'), ('free', 'c_mem'), ('内存泄漏', 'c_mem'), ('堆栈', 'c_mem'),
        ('文件', 'c_file'), ('fopen', 'c_file'), ('fgets', 'c_file'),
        ('宏', 'c_prep'), ('define', 'c_prep'), ('include', 'c_prep'), ('头文件', 'c_prep'), ('编译', 'c_prep'),
    ],
    'biology': [
        ('细胞器', 'bio_cell'), ('线粒体', 'bio_cell'), ('有丝分裂', 'bio_cell'), ('原核', 'bio_cell'), ('染色体', 'bio_cell'),
        ('主动运输', 'bio_membrane'), ('细胞膜', 'bio_membrane'), ('渗透', 'bio_membrane'), ('载体', 'bio_membrane'),
        ('酶', 'bio_enzyme'), ('ATP', 'bio_enzyme'), ('活化能', 'bio_enzyme'),
        ('光合', 'bio_photo'), ('光反应', 'bio_photo'), ('暗反应', 'bio_photo'), ('叶绿体', 'bio_photo'),
        ('呼吸', 'bio_resp'), ('无氧', 'bio_resp'), ('丙酮酸', 'bio_resp'), ('酵母', 'bio_resp'), ('乳酸', 'bio_resp'),
        ('DNA', 'bio_genetics'), ('转录', 'bio_genetics'), ('翻译', 'bio_genetics'), ('密码子', 'bio_genetics'), ('双螺旋', 'bio_genetics'),
        ('遗传', 'bio_mendel'), ('孟德尔', 'bio_mendel'), ('伴性', 'bio_mendel'), ('减数分裂', 'bio_mendel'), ('自交', 'bio_mendel'),
        ('内环境', 'bio_homeostasis'), ('神经', 'bio_homeostasis'), ('激素', 'bio_homeostasis'), ('免疫', 'bio_homeostasis'), ('胰岛素', 'bio_homeostasis'), ('反射', 'bio_homeostasis'),
        ('种群', 'bio_eco'), ('群落', 'bio_eco'), ('生态系统', 'bio_eco'), ('能量流动', 'bio_eco'), ('食物链', 'bio_eco'), ('K值', 'bio_eco'),
    ],
    'chemistry': [
        ('摩尔', 'chem_periodic'), ('周期律', 'chem_periodic'), ('同位素', 'chem_periodic'), ('原子半径', 'chem_periodic'),
        ('化学键', 'chem_bond'), ('离子键', 'chem_bond'), ('共价', 'chem_bond'), ('晶体', 'chem_bond'), ('氢键', 'chem_bond'),
        ('平衡', 'chem_equilibrium'), ('速率', 'chem_equilibrium'), ('转化率', 'chem_equilibrium'), ('勒夏特列', 'chem_equilibrium'),
        ('pH', 'chem_ph'), ('水解', 'chem_ph'), ('电离', 'chem_ph'), ('离子浓度', 'chem_ph'), ('电解质', 'chem_ph'),
        ('氧化', 'chem_redox'), ('还原', 'chem_redox'), ('电子转移', 'chem_redox'), ('配平', 'chem_redox'), ('化合价', 'chem_redox'),
        ('原电池', 'chem_electro'), ('电解', 'chem_electro'), ('电极', 'chem_electro'), ('燃料电池', 'chem_electro'), ('电镀', 'chem_electro'),
        ('有机', 'chem_organic'), ('同分异构', 'chem_organic'), ('官能团', 'chem_organic'), ('酯化', 'chem_organic'), ('银镜', 'chem_organic'),
        ('实验', 'chem_lab'), ('蒸馏', 'chem_lab'), ('过滤', 'chem_lab'), ('萃取', 'chem_lab'), ('滴定', 'chem_lab'),
    ],
}


def match_kps(text, subject=None, top=4, min_score=1):
    """按关键词命中数匹配知识点，返回 [(subject, kp, score)] 按分数降序。
    含符号/术语别名规则；只给了科目但没命中时返回 [(subject, None, 0)] 由调用方降级处理。"""
    _load_subjects()
    pool = [(s, kp) for s, sub in SUBJECTS.items()
            if subject is None or s == subject
            for kp in sub['kps'].values()]
    text_l = text.lower()
    scored = []
    for s, kp in pool:
        score = 0
        for kw in kp['keywords']:
            if kw.lower() in text_l:
                score += 2 + len(kw) * 0.1
        # 符号/别名规则：对候选知识点加分
        for tok, target in SYMBOL_RULES.get(s, []):
            if target == kp['id'] and tok.lower() in text_l:
                score += 2.5
        for w in _bigrams(text) & _bigrams(kp['name']):
            score += 0.05
        for err in kp['common_errors']:
            head = err[:6]
            if len(head) >= 4 and head in text_l:
                score += 1
        if score >= min_score:
            scored.append((s, kp, round(score, 2)))
    scored.sort(key=lambda x: -x[2])
    return scored[:top]


def generic_guidance(subject=None, qtype='proof'):
    """未命中知识点时的降级引导：数学题通用方法论（尤其证明题）。"""
    steps = [
        '先把题目条件和结论逐句"翻译"成数学语言：条件涉及哪些对象？结论等价于什么式子？',
        '从结论倒推：要证这个结论，通常需要哪些引理或中间步骤？（分析法）',
        '再用条件正推，与倒推的中间步骤"对接"（综合法）；卡住时考虑反证法或构造辅助对象。',
    ]
    if subject == 'calculus':
        steps += ['涉及极限/积分的证明，优先考虑：定义（ε-δ / ε-N）、夹逼、单调有界、中值定理、泰勒展开。']
    elif subject == 'linear_algebra':
        steps += ['矩阵证明题优先考虑：定义恒等变形、秩与可逆的等价刻画、特征值性质、对齐次方程组解空间的讨论。']
    return {
        'kp_name': '', 'guidance': steps,
        'explanation': '（该题暂未精确匹配到知识点，给出数学证明题的通用引导框架。）',
        'key_points': ['数学证明三步法：翻译条件结论 → 分析法倒推 → 综合法书写'],
        'followups': ['这题的条件里，哪个量最特殊？它能推出什么？', '结论中的式子能等价变形为哪个已知的定理形式？'],
        'sources': [],
    }


def prereq_closure(subject, kp_ids):
    """返回 kp_ids 及其全部前置知识的 id 集合（用于出卷与讲义选点）。"""
    sub = get_subject(subject)
    if not sub:
        return set(kp_ids)
    out = set()
    stack = [k for k in kp_ids if k in sub['kps']]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(sub['kps'][cur].get('prereqs', []))
    return out


def level_of(score):
    if score < 40:
        return '薄弱'
    if score < 70:
        return '一般'
    if score < 85:
        return '良好'
    return '掌握'


def weak_kps(sid, subject=None, top=6):
    """从学生掌握度中挑出最薄弱的知识点（未被触及的知识点视为未诊断，中低优先）。"""
    m = store.mastery_levels(sid)
    recs = [(kid, v) for kid, v in m.items()
            if subject is None or v.get('subject') == subject]
    weak = sorted(recs, key=lambda x: x[1]['score'])
    return [{'id': kid, 'subject': v.get('subject'), 'score': v['score'],
             'level': level_of(v['score']), 'hits': v['hits'], 'wrong': v['wrong']}
            for kid, v in weak[:top]]


def recommend_kps(sid, subject, n=4):
    """出卷/讲义选点：优先掌握度低的知识点；不足时用图谱中未测过的知识点补齐。"""
    weak = weak_kps(sid, subject=subject, top=n)
    chosen = [w['id'] for w in weak]
    if len(chosen) < n:
        sub = get_subject(subject)
        if sub:
            untouched = [kid for kid in sub['kps'] if kid not in chosen]
            chosen += untouched[:n - len(chosen)]
    return chosen[:n]


def kp_brief(subject, kp_id):
    kp = get_kp(subject, kp_id)
    if not kp:
        return {}
    return {'id': kp['id'], 'name': kp['name'], 'description': kp['description'],
            'key_points': kp['key_points'], 'common_errors': kp['common_errors'],
            'prereqs': kp.get('prereqs', [])}


def now_str():
    return time.strftime('%Y-%m-%d %H:%M', time.localtime())
