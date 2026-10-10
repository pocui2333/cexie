import os
import re
import json
import config
from core import llm_client
from typing import Dict, Any, Optional

def distill_knowledge_to_playbook(raw_text: str, source_title: Optional[str] = None, knowledge_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    使用 AI 将任意长文沟通技巧/恋爱攻略/社交指南自动脱水提炼为标准情景微策略卡，
    并自动持久化追加到 knowledge/playbooks.json 中。
    """
    if not raw_text or len(raw_text.strip()) < 15:
        return {"status": "error", "message": "输入内容过短，请提供有实质内容的沟通策略或技巧文章"}

    target_dir = knowledge_dir or config.KNOWLEDGE_DIR
    playbooks_path = os.path.join(target_dir, "playbooks.json")
    os.makedirs(target_dir, exist_ok=True)

    title_hint = f"文章参考标题: {source_title.strip()}\n" if source_title else ""
    prompt = (
        "你是一个专业的人际沟通与亲密关系心智分析专家。\n"
        "任务：请将以下沟通指南/社交心得/技巧文章深度消化，提炼为一张标准的情景微策略卡 (Micro-Playbook Card)。\n"
        f"{title_hint}\n"
        "【待提炼文章内容】:\n"
        f"{raw_text[:4000]}\n\n"
        "请严格输出如下 JSON 格式，绝不包含任何 markdown 代码块或额外说明：\n"
        "{\n"
        '  "id": "playbook_英文小写下划线唯一标识 (如 playbook_first_date_prep)",\n'
        '  "category": "emotional 或 dynamic 或 tactics 或 boundary 或 psychology",\n'
        '  "title": "精炼策略标题 (12字以内，如 细节赞美与真诚欣赏)",\n'
        '  "triggers": ["提取10-18个该场景下对方最可能说出的高频口语词、情绪词或话题关键词"],\n'
        '  "taboo": "避坑雷区（明确列出该场景绝对严禁犯的错，如长辈式说教、理性纠错、扫兴、油腻等）",\n'
        '  "principle": "核心心法（50字以内的社交沟通本质认知，为何要这样处理）",\n'
        '  "tactics": "实操支点（具体的接话切入角度、破局方法与推进逻辑）"\n'
        "}"
    )

    if not llm_client.is_enabled():
        return {"status": "error", "message": "未配置 LLM_API_KEY，无法使用 AI 提炼知识卡"}

    try:
        content = llm_client.chat_completion(
            [
                {"role": "system", "content": "你只输出严格的单个 JSON 对象，不加任何思考过程或解释说明。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3, max_tokens=600, timeout=15.0
        )
        card = llm_client.extract_json(content)
        if not isinstance(card, dict):
            return {"status": "error", "message": "AI 输出无法解析为 JSON，请稍后重试"}
        if not card.get("title") or not card.get("principle"):
            return {"status": "error", "message": "AI 提炼结果不完整，请稍后重试"}

        # 读取现有 playbooks
        playbooks = []
        if os.path.exists(playbooks_path):
            try:
                with open(playbooks_path, "r", encoding="utf-8") as f:
                    playbooks = json.load(f)
            except Exception as e:
                # 读取失败时绝不覆盖写回，避免清空已有策略库
                return {"status": "error", "message": f"现有 playbooks.json 读取失败，已中止写入: {e}"}

        # 避免 ID 冲突
        card_id = card.get("id", f"playbook_custom_{len(playbooks)+1}")
        if any(p.get("id") == card_id for p in playbooks):
            card_id = f"{card_id}_{len(playbooks)+1}"
        card["id"] = card_id

        playbooks.append(card)

        # 持久化写回
        with open(playbooks_path, "w", encoding="utf-8") as f:
            json.dump(playbooks, f, ensure_ascii=False, indent=2)

        return {
            "status": "success",
            "message": f"已成功将《{card['title']}》提炼为情景微策略卡并入库！",
            "card": card,
            "total_playbooks": len(playbooks)
        }
    except Exception as e:
        return {"status": "error", "message": f"AI 提炼失败: {e}"}
