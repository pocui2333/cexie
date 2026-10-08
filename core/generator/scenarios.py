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
    u1 = "确实是这么个理，按你自己最顺手的节奏对付就完事了"
    u2 = "我平时也差不多这样，怎么省心怎么来，不折腾自己"
    u3 = "先把眼前事对付明白，回头该吃吃该歇歇"

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
        {"sub_goal": "原生原话", "text": u1, "rationale": "基于历史发言习惯与真实性格的第一反应原话"},
        {"sub_goal": "原生原话", "text": u2, "rationale": "贴合性格底色的真实大白话回复"},
        {"sub_goal": "原生原话", "text": u3, "rationale": "随性直白的生活大白话候选"},
        {"sub_goal": "幽默接梗", "text": "哈哈哈哈你这路子挺稳妥的，突出一个省心踏实", "rationale": "基于原话微调：打趣老友日常节奏"},
        {"sub_goal": "情绪撑腰", "text": "犯不上自己跟自己较劲，咋得劲咋整就完事了，不用在意外面怎么说", "rationale": "基于原话微调：给足做自己底气与护短"},
        {"sub_goal": "互动推进", "text": "今天先把手头事理顺，有啥新情况随时发来唠唠", "rationale": "基于原话微调：开放式生活分享邀请"}
    ]
