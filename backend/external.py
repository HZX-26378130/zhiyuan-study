# -*- coding: utf-8 -*-
"""外部 AI 引导（借力模式）：
① 根据学生问题 + 档案生成可直接复制到 DeepSeek/网页AI 的引导式学习提示词；
② 学生把外部 AI 的回答粘贴回来，系统自动收纳总结（关联考点/要点/质量评价）并记忆归档，随时可查。

⚠️ 定位声明：这是阉割版——外部网页 AI 是无状态的、无法持续跟随学生档案、也不能自动改作业。
真正的学习模型应由 agent 驱动多个 skill（学习计划/每日课程/错题管理/出题批改）协同完成，
参考：yoli-mi/good-learning、Miaotofu01/Study-Mate、EricWang1358/dsh-web-studyhub。
本模块吸收了 good-learning 的"完整例题→填步→变式→混合回顾"四步法与错题字段规范。"""
import time
import uuid

from . import knowledge, llm, memory, store

MAX_ITEMS = 100

DISCLAIMER = (
    '这是阉割版：把提示词带去网页 AI（DeepSeek 等）只是借外部模型的手，它记不住你的档案、'
    '不会自动改你的作业、也无法持续跟进。真正的学习模型需要 agent 驱动多个 skill 协同'
    '（定学习路线 → 逐日讲解 → 错题管理 → 变式出题，如 good-learning / Study-Mate 的做法）。'
    '知源学伴的完整闭环（档案画像/错题本/积分/全班反馈学习）都在向这个方向演进。'
)

REFERENCES = [
    {'name': 'yoli-mi/good-learning（结构化学习计划·每日课程·错题管理 agent skill）',
     'url': 'https://github.com/yoli-mi/good-learning-skill'},
    {'name': 'Miaotofu01/Study-Mate（定路线·讲知识·做项目·间隔复习的 AI 学习搭档）',
     'url': 'https://github.com/Miaotofu01/Study-Mate'},
    {'name': 'EricWang1358/dsh-web-studyhub（DSH 插件生态的 Web 学习中心）',
     'url': 'https://github.com/EricWang1358/dsh-web-studyhub/releases'},
]


def _path(sid):
    return store._path(sid, 'external.json')


def _load(sid):
    return store._read_json(_path(sid), {'items': []})


def _save(sid, d):
    store._write_json(_path(sid), d)


def _weak_line(sid):
    try:
        ctx = memory.teaching_context(sid, max_prefs=3)
        # 只取薄弱点段落，避免提示词过长
        for part in ctx.split('\n\n'):
            if part.startswith('学生当前最薄弱知识点'):
                return part
    except Exception:
        pass
    return ''


def build_prompt(sid, question, subject=None, mode='guide'):
    """生成可复制到外部网页 AI 的引导式学习提示词。返回 {prompt, kp_name, matched}。"""
    question = (question or '').strip()
    if len(question) < 4:
        raise ValueError('问题太短，先写清楚要问什么')
    matched = knowledge.match_kps(question, subject=subject, top=1)
    kp_name = matched[0][1]['name'] if matched else ''
    subj_name = knowledge.subjects().get(matched[0][0], '') if matched else (subject and knowledge.subjects().get(subject) or '')
    weak = _weak_line(sid)

    if mode == 'explain':
        style = (
            '## 教学方式（讲解模式）\n'
            '- 给出完整讲解：定义与适用条件 → 思路 → 完整推导（每一步都说明"为什么走这一步"）→ 结论 → 易错点。\n'
            '- 按"完整例题及每步理由 → 同构填步题（关键步骤留空让我补）→ 改变条件的独立变式 → 混合回顾"组织例题。\n'
            '- 如果我是零基础：从直觉和几何意义讲起，少用术语；如果我已入门：压缩讲解、加练习、提高起始难度。'
        )
    else:
        style = (
            '## 教学方式（引导模式，重要）\n'
            '- 绝对不要一次性给出完整答案。你每轮只推进一小步，然后停下向我提问，等我的回答。\n'
            '- 第一轮只做三件事：① 用一句话点明考察的知识点；② 给出解题的整体框架（2-3 步）；'
            '③ 提出第一个引导问题让我自己迈出第一步。\n'
            '- 我每答一步，你只评价这一步（对：肯定并给下一步；错：不直接纠正，先反问让我自己发现矛盾）。\n'
            '- 关键结论必须由我自己说出来；确认我理解后，再按"完整例题→填步题→变式→混合回顾"给我巩固。'
        )

    prompt = (
        '你是一位严谨耐心的辅导老师，请用中文引导我学习。我的水平画像与要求如下：\n\n'
        '## 我的问题\n' + question + '\n\n'
        '## 我的背景\n'
        + ('- 相关考点：%s（%s）\n' % (kp_name, subj_name) if kp_name else '') +
        (('- %s\n' % weak) if weak else '') +
        '- 数学式请用直观记号，必要时给我几何/生活直觉。\n\n'
        + style + '\n\n'
        '## 输出格式\n'
        '【考点】一句话\n【引导】按上面教学方式输出本轮内容\n【反问】留给我思考的问题\n'
        '【要点】本轮必须记住的结论（若我尚未自己得出，留空并改成反问）\n'
        '【追问】我可以继续问什么\n\n'
        '请开始第一轮。'
    )
    return {'prompt': prompt, 'kp_name': kp_name, 'matched': bool(matched),
            'disclaimer': DISCLAIMER, 'references': REFERENCES}


def save_answer(sid, question, subject, answer, model_used=''):
    """收纳外部 AI 的回答：AI 总结 + 关联考点 + 记忆归档。返回归档条目（含总结）。"""
    question = (question or '').strip()
    answer = (answer or '').strip()
    if len(answer) < 20:
        raise ValueError('回答太短，粘贴外部 AI 的完整回复再提交')
    matched = knowledge.match_kps(question, subject=subject, top=1)
    subject_k, kp = matched[0][0], matched[0][1] if matched else (None, None)

    summary = {}
    if llm.available():
        try:
            summary = llm.chat_json([
                {'role': 'system', 'content': '你是学习助教，负责"收纳"学生从外部AI带回来的回答。'},
                {'role': 'user', 'content':
                    '学生问：%s\n外部AI的回答（节选）：%s\n\n'
                    '请输出 JSON：{"tldr": "一句话总结这段回答讲了什么（60字内）", '
                    '"key_points": ["学生应记住的要点，2-4条"], '
                    '"style": "socratic|direct", "quality": "1-5分整数", '
                    '"quality_note": "一句话点评（是否真的引导式？内容可靠吗？）", '
                    '"followup": "建议学生接下来追问或练习什么"}' % (question[:200], answer[:3000])
                }], temperature=0.2, max_tokens=900) or {}
        except llm.LLMError:
            summary = {}

    d = _load(sid)
    item = {
        'id': uuid.uuid4().hex[:12], 'ts': time.time(),
        'question': question[:300], 'subject': subject_k or subject or '',
        'kp_id': (kp or {}).get('id', ''), 'kp_name': (kp or {}).get('name', ''),
        'model': str(model_used or '外部AI')[:30], 'answer': answer[:8000],
        'tldr': str(summary.get('tldr', ''))[:120],
        'key_points': [str(k)[:150] for k in (summary.get('key_points') or []) if k][:4],
        'style': summary.get('style', ''), 'quality': summary.get('quality', ''),
        'quality_note': str(summary.get('quality_note', ''))[:150],
        'followup': str(summary.get('followup', ''))[:200],
    }
    d['items'] = ([item] + d.get('items', []))[:MAX_ITEMS]
    _save(sid, d)
    store.log_event(sid, 'external', {'q': question[:120], 'model': item['model'],
                                      'kp': item['kp_name'], 'tldr': item['tldr'][:80]})
    # 有总结价值时，喂给个人记忆（作为一条反馈记录，参与后续反思）
    if item['tldr']:
        try:
            memory.add_feedback(sid, 'external', item['kp_name'] or question[:20],
                                1 if str(summary.get('quality', 3)).startswith(('4', '5')) else 0,
                                '外部AI(%s)：%s' % (item['model'], item['tldr']))
        except Exception:
            pass
    return item


def list_items(sid):
    d = _load(sid)
    out = []
    for it in d.get('items', []):
        out.append({k: it.get(k) for k in ('id', 'ts', 'question', 'kp_name', 'model', 'tldr', 'quality')})
    return {'items': out, 'total': len(out), 'disclaimer': DISCLAIMER, 'references': REFERENCES}


def get_item(sid, item_id):
    for it in _load(sid).get('items', []):
        if it['id'] == item_id:
            return it
    return None


def remove_item(sid, item_id):
    d = _load(sid)
    n = len(d.get('items', []))
    d['items'] = [it for it in d.get('items', []) if it['id'] != item_id]
    _save(sid, d)
    return n - len(d['items'])
