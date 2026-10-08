"""
DualTrackGenerator: Coordinates LLM generation and Heuristic Rule synthesis,
ensuring strict 2x3 matrix compliance and linguistic guardrails.
"""
import os
import json
import re
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
import config
from core.contracts import GenerationOption, DualTrackResult
from core.generator.guardrails import apply_linguistic_guardrails
from core.generator.prompts import build_system_prompt, build_user_prompt
from core.generator.scenarios import synthesize_scenario_options

class DualTrackGenerator:
    """
    双轨 6 选项生成引擎 (The 2x3 Matrix Engine)
    """
    def __init__(self, ego_dir: str, contacts_dir: str, knowledge_dir: str):
        self.ego_dir = ego_dir
        self.contacts_dir = contacts_dir
        self.knowledge_dir = knowledge_dir

    def generate(
        self,
        target_name: str,
        incoming_text: str,
        memory_episodes: List[Dict[str, Any]],
        context_text: Optional[str] = None
    ) -> DualTrackResult:
        rules = self._load_rules(target_name)
        text_clean = incoming_text.strip()
        ego_utterances = self._load_recent_ego_utterances(target_name)

        options_data = None
        if config.LLM_API_KEY:
            try:
                options_data = self._call_llm(target_name, text_clean, memory_episodes, rules, context_text, ego_utterances)
            except Exception as e:
                print(f"[LLM Generate Error] {e}")

        if not options_data or len(options_data) != 6:
            options_data = synthesize_scenario_options(target_name, text_clean, memory_episodes, rules, context_text, ego_utterances)

        options: List[GenerationOption] = []
        for idx, item in enumerate(options_data, start=1):
            filtered_text = apply_linguistic_guardrails(item["text"], rules)
            options.append(GenerationOption(
                slot_id=idx,
                track="native" if idx <= 3 else "evolved",
                sub_goal=item["sub_goal"],
                reply_text=filtered_text,
                tactical_rationale=item["rationale"]
            ))

        return DualTrackResult(
            target_name=target_name,
            incoming_context=text_clean,
            options=options
        )

    def _load_recent_ego_utterances(self, target_name: str, limit: int = 8) -> List[str]:
        db_path = os.path.join(self.contacts_dir, target_name, "index.db")
        if not os.path.exists(db_path):
            return []
        results = []
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT facts_summary FROM episode_records 
                WHERE facts_summary LIKE '%我:%' 
                ORDER BY id DESC LIMIT 50
            """)
            for row in cur.fetchall():
                matches = re.findall(r'我:\s*([^;。\n]+)', row[0])
                for m in matches:
                    cleaned = m.strip()
                    if cleaned and cleaned not in results and 2 <= len(cleaned) <= 60 and "暂未回复" not in cleaned:
                        results.append(cleaned)
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
            conn.close()
        except Exception:
            pass
        return results

    def _call_llm(
        self,
        target_name: str,
        incoming_text: str,
        memory: List[Dict[str, Any]],
        rules: Dict[str, Any],
        context_text: Optional[str] = None,
        ego_utterances: Optional[List[str]] = None
    ) -> Optional[List[Dict[str, str]]]:
        import ssl
        try:
            import certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ssl_ctx = ssl._create_unverified_context()

        ego_profile = self._load_ego_profile()
        target_dossier = self._load_target_dossier(target_name)

        system_prompt = build_system_prompt(target_name, rules, ego_profile, target_dossier)
        user_prompt = build_user_prompt(incoming_text, memory, context_text, target_dossier, ego_utterances)

        url = f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}"
        }
        body = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 800
        }

        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            
            # 提取 JSON 数组
            match = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
            if match:
                content = match.group(0)

            # 清理常见非法尾随逗号与格式瑕疵
            cleaned_json = re.sub(r',\s*([\]}])', r'\1', content)
            try:
                parsed = json.loads(cleaned_json, strict=False)
            except Exception:
                try:
                    parsed = json.loads(content, strict=False)
                except Exception:
                    parsed = None

            if isinstance(parsed, list) and len(parsed) == 6:
                return parsed
        return None

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
                    rules["taboo_words"].extend(t_rules.get("taboo_words", []))
            except Exception:
                pass
        return rules
