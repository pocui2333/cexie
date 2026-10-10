"""
DualTrackGenerator: Coordinates LLM generation and Heuristic Rule synthesis,
producing 4 situational reply options plus free-form insights, with linguistic guardrails.
"""
import logging
import os
import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from core import llm_client
from core.contracts import GenerationOption, DualTrackResult
from core.memory import EntityMemoryRetriever
from core.generator.guardrails import apply_linguistic_guardrails
from core.generator.prompts import build_system_prompt, build_user_prompt
from core.generator.scenarios import synthesize_scenario_options
from core.knowledge.term_search import extract_and_calibrate_terms
from core.knowledge.context_enhancer import build_environmental_context
from core.knowledge.retriever import KnowledgeRetriever

logger = logging.getLogger(__name__)

_SENTIMENT_CACHE: Dict[str, bool] = {}

OPTION_COUNT = 4
MAX_INSIGHTS = 4


def parse_generation_output(content: str) -> Optional[Dict[str, Any]]:
    """解析模型输出 {insights, options}；回复条数不足时返回 None 走离线兜底"""
    parsed = llm_client.extract_json(content, want="object")
    if not isinstance(parsed, dict):
        return None
    options = [o for o in parsed.get("options") or [] if isinstance(o, dict) and str(o.get("text", "")).strip()]
    if len(options) < OPTION_COUNT:
        return None
    insights = []
    for it in parsed.get("insights") or []:
        if not isinstance(it, dict):
            continue
        label, text = str(it.get("label", "")).strip(), str(it.get("text", "")).strip()
        if label and text:
            insights.append({"label": label, "text": text})
    return {"insights": insights[:MAX_INSIGHTS], "options": options[:OPTION_COUNT]}


class DualTrackGenerator:
    """
    4 条回复建议 + 本轮洞察生成引擎 (标签均由模型按当轮对话现起，不设固定槽位)
    """
    def __init__(self, ego_dir: str, contacts_dir: str, knowledge_dir: str):
        self.ego_dir = ego_dir
        self.contacts_dir = contacts_dir
        self.knowledge_dir = knowledge_dir
        self.knowledge_retriever = KnowledgeRetriever(self.knowledge_dir)
        self.memory = EntityMemoryRetriever(self.contacts_dir)

    def generate(
        self,
        target_name: str,
        incoming_text: str,
        memory_episodes: List[Dict[str, Any]],
        context_text: Optional[str] = None,
        today_memory: Optional[List[Dict[str, Any]]] = None,
        is_replied: bool = False,
        last_ego_text: Optional[str] = None
    ) -> DualTrackResult:
        rules = self._load_rules(target_name)
        text_clean = incoming_text.strip()
        ego_profile = self._load_ego_profile()

        # 各路上下文互不依赖 (本地 SQLite / 百科 / 天气)，并发获取以压低总延迟
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_ego = pool.submit(self.memory.get_recent_ego_utterances, target_name, 16)
            f_qa = pool.submit(self.memory.retrieve_qa_scene_snippets, target_name, text_clean, 6)
            # 动态专有名词检索与我方认知边界校准 (防止知识库盲从与凭空瞎编)
            f_terms = pool.submit(extract_and_calibrate_terms, text_clean, ego_profile)
            # 动态时空常识、专属纪念日/生日与城市天气背景 (若无相关记录则静默跳过)
            f_env = pool.submit(build_environmental_context, target_name, self.contacts_dir)
            raw_ego_utterances = f_ego.result()
            raw_qa_snippets = f_qa.result()
            calibrated_terms = f_terms.result()
            env_context = f_env.result()

        # 我方历史原话与问答切片中的负向句子合并为一次 AI 判定后剔除
        ego_utterances, qa_snippets = self._filter_style_samples(raw_ego_utterances, raw_qa_snippets)

        # 动态通用社交与情商知识库策略检索
        knowledge_guidance = self.knowledge_retriever.retrieve_guidance(text_clean)

        llm_res = None
        if llm_client.is_enabled():
            try:
                llm_res = self._call_llm(
                    target_name, text_clean, memory_episodes, rules,
                    context_text, ego_utterances, qa_snippets, calibrated_terms, env_context, knowledge_guidance,
                    today_memory=today_memory, is_replied=is_replied, last_ego_text=last_ego_text,
                    ego_profile=ego_profile
                )
            except Exception as e:
                logger.error("[LLM Generate Error] %s", e)

        if llm_res:
            insights = llm_res["insights"]
            options_data = llm_res["options"]
        else:
            # 离线兜底不编造洞察，前端无洞察时自动隐藏该区域
            insights = []
            options_data = synthesize_scenario_options(
                target_name, text_clean, memory_episodes, rules,
                context_text, ego_utterances, qa_snippets, calibrated_terms
            )

        options: List[GenerationOption] = []
        for idx, item in enumerate(options_data, start=1):
            filtered_text = apply_linguistic_guardrails(str(item.get("text", "")), rules)
            options.append(GenerationOption(
                slot_id=idx,
                sub_goal=str(item.get("label") or item.get("sub_goal") or "").strip(),
                reply_text=filtered_text,
                tactical_rationale=item.get("rationale", "")
            ))

        return DualTrackResult(
            target_name=target_name,
            incoming_context=text_clean,
            options=options,
            insights=insights
        )

    def _filter_style_samples(
        self, ego_utterances: List[str], qa_snippets: List[Dict[str, str]], limit_ego: int = 8, limit_qa: int = 3
    ) -> Tuple[List[str], List[Dict[str, str]]]:
        candidates = list(dict.fromkeys(ego_utterances + [s["ego_replied"] for s in qa_snippets]))
        passed = set(self._filter_positive_neutral_by_ai(candidates))
        return (
            [u for u in ego_utterances if u in passed][:limit_ego],
            [s for s in qa_snippets if s["ego_replied"] in passed][:limit_qa],
        )

    def _filter_positive_neutral_by_ai(self, items: List[str]) -> List[str]:
        """
        AI 动态情感与社交倾向过滤 (带内存缓存与极速短路):
        - 判定为【负向】（抱怨、扫兴、挑刺、泼冷水、消极摆烂、刻薄、烦躁、攻击性）坚决过滤剔除
        - 仅保留【正向】与【中性】句子
        """
        if not items:
            return items

        uncached = [it for it in items if it not in _SENTIMENT_CACHE]
        if uncached and llm_client.is_enabled():
            prompt = (
                "请对以下历史聊天句子进行情感与社交倾向判断。\n"
                "AI 任务：如果句子带有【负向】倾向（包括抱怨、扫兴、挑刺、泼冷水、消极摆烂、刻薄、烦躁、攻击性），判定为负向并过滤剔除；\n"
                "只保留【正向】或【中性】（日常分享、随性交流、就事论事）的句子。\n\n"
                "待判断句子：\n" +
                "\n".join([f"{i+1}. {txt}" for i, txt in enumerate(uncached)]) +
                "\n\n请严格以 JSON 数组形式只返回通过筛选（正向或中性）的原始句子序号，格式如：[1, 3]"
            )
            try:
                content = llm_client.chat_completion(
                    [{"role": "user", "content": prompt}], temperature=0.1, max_tokens=120, timeout=2.5
                )
                indices = llm_client.extract_json(content, want="array") or []
                passed_set = {uncached[i - 1] for i in indices if isinstance(i, int) and 1 <= i <= len(uncached)}
                for it in uncached:
                    _SENTIMENT_CACHE[it] = it in passed_set
            except Exception:
                # 超时或网络异常时本轮降级放行 (不写缓存，下次再判)，保证主流程极速响应
                pass

        return [it for it in items if _SENTIMENT_CACHE.get(it, True)]

    def _call_llm(
        self,
        target_name: str,
        incoming_text: str,
        memory: List[Dict[str, Any]],
        rules: Dict[str, Any],
        context_text: Optional[str] = None,
        ego_utterances: Optional[List[str]] = None,
        qa_snippets: Optional[List[Dict[str, str]]] = None,
        calibrated_terms: Optional[List[Dict[str, str]]] = None,
        env_context: Optional[str] = None,
        knowledge_guidance: Optional[Dict[str, str]] = None,
        today_memory: Optional[List[Dict[str, Any]]] = None,
        is_replied: bool = False,
        last_ego_text: Optional[str] = None,
        ego_profile: str = ""
    ) -> Optional[Dict[str, Any]]:
        target_dossier = self._load_target_dossier(target_name)

        system_prompt = build_system_prompt(target_name, rules, ego_profile, target_dossier)
        user_prompt = build_user_prompt(
            incoming_text, memory, context_text,
            ego_utterances, qa_snippets, calibrated_terms, env_context, knowledge_guidance,
            today_memory=today_memory, is_replied=is_replied, last_ego_text=last_ego_text
        )

        content = llm_client.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7, max_tokens=800, timeout=12.0
        )

        return parse_generation_output(content)

    def _load_ego_profile(self) -> str:
        path = os.path.join(self.ego_dir, "profile.md")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def _load_target_dossier(self, target_name: str) -> str:
        path = os.path.join(self.contacts_dir, target_name, "dossier.md")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def _load_rules(self, target_name: str) -> Dict[str, Any]:
        rules = {"taboo_words": [], "style_preference": "接地气、逗号断句、无标点叹号"}
        ego_rules_path = os.path.join(self.ego_dir, "rules.json")
        if os.path.exists(ego_rules_path):
            try:
                with open(ego_rules_path, "r", encoding="utf-8") as f:
                    rules.update(json.load(f))
            except Exception:
                pass

        target_rules_path = os.path.join(self.contacts_dir, target_name, "rules.json")
        if os.path.exists(target_rules_path):
            try:
                with open(target_rules_path, "r", encoding="utf-8") as f:
                    t_rules = json.load(f)
                # 联系人规则覆盖全局规则；禁用词类列表取并集
                for key in ("taboo_words", "banned_phrases"):
                    merged = list(rules.get(key, [])) + list(t_rules.get(key, []))
                    t_rules[key] = list(dict.fromkeys(merged))
                rules.update(t_rules)
            except Exception:
                pass
        return rules
