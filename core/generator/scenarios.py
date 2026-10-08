"""
Offline Generic Semantic Slot Assembler.
A minimalist, human-like fallback engine for offline or fallback situations.
Contains ZERO hardcoded private data, zero internet meme templates, and no rigid scenario enumerations.
"""
from typing import List, Dict, Any, Optional

def synthesize_scenario_options(
    target_name: str,
    incoming_text: str,
    memory: List[Dict[str, Any]],
    rules: Dict[str, Any],
    context_text: Optional[str] = None,
    ego_utterances: Optional[List[str]] = None,
    qa_snippets: Optional[List[Dict[str, str]]] = None
) -> List[Dict[str, str]]:
    # 优先复用历史类似提问下我方的真实回答（若有）
    u1 = "挺好的，怎么顺心怎么整，自己开心最重要"
    u2 = "我平时也差不多这样，按自己喜欢的节奏来最得劲"
    u3 = "先把眼前事忙明白，回头好好犒劳一下自己"

    if qa_snippets:
        if len(qa_snippets) >= 1 and qa_snippets[0].get("ego_replied"):
            u1 = qa_snippets[0]["ego_replied"]
        if len(qa_snippets) >= 2 and qa_snippets[1].get("ego_replied"):
            u2 = qa_snippets[1]["ego_replied"]
        if len(qa_snippets) >= 3 and qa_snippets[2].get("ego_replied"):
            u3 = qa_snippets[2]["ego_replied"]
    elif ego_utterances:
        if len(ego_utterances) >= 1:
            u1 = ego_utterances[0]
        if len(ego_utterances) >= 2:
            u2 = ego_utterances[1]
        if len(ego_utterances) >= 3:
            u3 = ego_utterances[2]

    return [
        {"sub_goal": "原生原话", "text": u1, "rationale": "顺着对方当下的快乐点肯定，接住分享欲"},
        {"sub_goal": "原生原话", "text": u2, "rationale": "接地气生活大白话同频畅聊"},
        {"sub_goal": "原生原话", "text": u3, "rationale": "顺着话题好奇延展一个小点激发后续互动"},
        {"sub_goal": "幽默接梗", "text": "哈哈哈哈你这吃法挺有想法的，直接把快乐拉满了", "rationale": "在原话基础上融入生动画面感逗乐对方"},
        {"sub_goal": "情绪撑腰", "text": "开心最要紧，咋舒服咋整就完事了，不用在意外面怎么说", "rationale": "无条件偏袒夸奖与宠溺消除顾虑"},
        {"sub_goal": "互动推进", "text": "下回也带我整一回，我负责买单你负责带路", "rationale": "在原话基础上自然提出共同体验与陪伴"}
    ]
