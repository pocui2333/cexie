"""
纯函数与存储层回归测试 (无需微信窗口与网络)。运行: python3 -m unittest discover -s tests
"""
import datetime
import json
import os
import shutil
import tempfile
import unittest

from capture.names import is_contact_match
from capture.wechat_driver import _group_turns, _result_from_llm, _result_from_turns
from core import llm_client, store
from core.contracts import NO_REPLY
from core.generator.engine import parse_generation_output
from core.generator.guardrails import apply_linguistic_guardrails
from core.knowledge.context_enhancer import get_temporal_context
from ingestion.episodic_distiller import EpisodicDistiller


class ContactMatchTest(unittest.TestCase):
    def test_exact_and_normalized(self):
        self.assertTrue(is_contact_match("张伟", "张伟"))
        self.assertTrue(is_contact_match(" 家人群(12) ", "家人群"))
        self.assertTrue(is_contact_match("家人群（3）", "家人群"))

    def test_rejects_similar_names(self):
        self.assertFalse(is_contact_match("李小明", "王小明"))
        self.assertFalse(is_contact_match("张伟家人群", "张伟"))
        self.assertFalse(is_contact_match("刘博士さん", "刘博士"))

    def test_missing_is_not_match(self):
        self.assertFalse(is_contact_match(None, "张伟"))
        self.assertFalse(is_contact_match("", "张伟"))


class SolarTermTest(unittest.TestCase):
    def term(self, iso):
        return get_temporal_context(datetime.datetime.fromisoformat(iso + "T12:00"))["festival_and_term"]

    def test_only_within_window(self):
        self.assertIn("小寒", self.term("2026-01-06"))
        self.assertIn("大寒", self.term("2026-01-21"))
        self.assertIn("寒露", self.term("2026-10-08"))
        self.assertEqual(self.term("2026-01-25"), "常规生活时序")
        self.assertEqual(self.term("2026-03-01"), "常规生活时序")
        self.assertNotIn("寒露", self.term("2026-10-30"))


class GuardrailsTest(unittest.TestCase):
    def test_keeps_decimals_and_urls(self):
        out = apply_linguistic_guardrails("3.5折。去 www.xx.com 看看!", {})
        self.assertIn("3.5折", out)
        self.assertIn("www.xx.com", out)
        self.assertNotIn("。", out)
        self.assertNotIn("!", out)

    def test_rules_banned_phrases_and_emoji(self):
        out = apply_linguistic_guardrails("在吗，今天吃火锅😀", {"banned_phrases": ["在吗"]})
        self.assertEqual(out, "今天吃火锅")


class ExtractJsonTest(unittest.TestCase):
    def test_fenced_trailing_comma(self):
        self.assertEqual(llm_client.extract_json('```json\n{"a": [1, 2,],}\n```'), {"a": [1, 2]})

    def test_array_and_garbage(self):
        self.assertEqual(llm_client.extract_json("结果: [1, 3]", want="array"), [1, 3])
        self.assertIsNone(llm_client.extract_json("no json here"))


class StoreTest(unittest.TestCase):
    def test_rejects_traversal(self):
        for bad in ["../x", "a/b", ".hidden", "", "  ", "x" * 65]:
            with self.assertRaises(store.InvalidContactName):
                store.contact_dir(bad, "/tmp/contacts")
        self.assertTrue(store.contact_dir("张伟", "/tmp/contacts").endswith("/张伟"))


class TurnParsingTest(unittest.TestCase):
    def els(self, *rows):
        return [(role, txt, {"y": y}) for role, txt, y in rows]

    def test_pending_collects_target_after_last_ego(self):
        turns = _group_turns(self.els(
            ("TARGET", "早", 0.8), ("EGO", "早啊", 0.7), ("TARGET", "吃了吗", 0.5), ("TARGET", "我吃火锅", 0.45)
        ))
        res = _result_from_turns(turns, "张伟")
        self.assertEqual(res.case_type, 2)
        self.assertEqual(res.ego_text, NO_REPLY)
        self.assertEqual(res.incoming_text.split("\n"), ["吃了吗", "我吃火锅"])

    def test_replied(self):
        turns = _group_turns(self.els(("TARGET", "吃了吗", 0.6), ("EGO", "吃了", 0.4)))
        res = _result_from_turns(turns, "张伟")
        self.assertEqual(res.case_type, 1)
        self.assertEqual(res.ego_text, "吃了")
        self.assertEqual(res.incoming_text, "吃了吗")


    def test_pending_includes_all_target_bubbles_below_my_last_reply(self):
        # 我最后一次回复下方，对方的所有消息 (含时间戳隔开的多段) 都算对方新消息
        turns = _group_turns(self.els(
            ("EGO", "旧回复", 0.9), ("TARGET", "旧消息", 0.85), ("EGO", "早啊", 0.7),
            ("TARGET", "吃了吗", 0.6), ("TIME", "12:30", 0.5), ("TARGET", "[图片: 火锅]", 0.45), ("TARGET", "超好吃", 0.4)
        ))
        res = _result_from_turns(turns, "张伟")
        self.assertEqual(res.reply_status, "pending")
        self.assertEqual(res.incoming_text.split("\n"), ["吃了吗", "[图片: 火锅]", "超好吃"])

    def test_replied_includes_all_my_bubbles_below_their_last_message(self):
        turns = _group_turns(self.els(
            ("EGO", "旧回复", 0.9), ("TARGET", "吃了吗", 0.7), ("TARGET", "我吃火锅", 0.65),
            ("EGO", "吃了", 0.5), ("EGO", "你在哪吃", 0.45)
        ))
        res = _result_from_turns(turns, "张伟")
        self.assertEqual(res.reply_status, "replied")
        self.assertEqual(res.ego_text.split("\n"), ["吃了", "你在哪吃"])
        self.assertEqual(res.incoming_text.split("\n"), ["吃了吗", "我吃火锅"])

    def test_llm_path_display_fields_follow_geometry(self):
        # 模型返回的展示字段不可靠 (已回复时常给空/旧的对方消息)，只采纳其对话流水
        turns = _group_turns(self.els(("TARGET", "吃了吗", 0.6), ("EGO", "吃了", 0.4)))
        llm = {"incoming_text": "", "ego_text": "早啊", "reply_status": "pending", "dialogue_context": "[张伟]: 吃了吗\n[我]: 吃了"}
        res = _result_from_llm(llm, "张伟", turns)
        self.assertEqual((res.incoming_text, res.ego_text, res.reply_status), ("吃了吗", "吃了", "replied"))
        self.assertEqual(res.dialogue_context, llm["dialogue_context"])


class GenerationParseTest(unittest.TestCase):
    def opts(self, n):
        return [{"label": f"打法{i}", "text": f"回复{i}", "rationale": "r"} for i in range(n)]

    def test_dynamic_labels_and_trims_to_four(self):
        raw = json.dumps({
            "insights": [{"label": "在晒手艺", "text": "想被夸"}, {"label": "", "text": "缺标签丢弃"}, "垃圾"],
            "options": self.opts(5),
        }, ensure_ascii=False)
        res = parse_generation_output(raw)
        self.assertEqual(res["insights"], [{"label": "在晒手艺", "text": "想被夸"}])
        self.assertEqual([o["label"] for o in res["options"]], ["打法0", "打法1", "打法2", "打法3"])

    def test_too_few_options_falls_back(self):
        self.assertIsNone(parse_generation_output(json.dumps({"insights": [], "options": self.opts(3)})))
        self.assertIsNone(parse_generation_output("不是 JSON"))

class DistillerDedupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "张伟"))
        self.d = EpisodicDistiller(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def count_episodes(self):
        with store.connect("张伟", self.dir) as conn:
            return conn.execute("SELECT COUNT(*) FROM episode_records").fetchone()[0]

    def test_same_screen_recorded_once(self):
        turns = [{"role": "TARGET", "text": "今天去吃火锅了"}, {"role": "EGO", "text": "哪家啊"}]
        self.assertEqual(self.d.record_turns("张伟", turns)["status"], "recorded")
        self.assertEqual(self.d.record_turns("张伟", turns)["status"], "unchanged")
        res = self.d.record_turns("张伟", turns + [{"role": "TARGET", "text": "海底捞"}])
        self.assertEqual(res["new_count"], 1)
        self.assertEqual(self.count_episodes(), 2)

    def test_checkpoint_keeps_newest_in_order(self):
        sandbox = os.path.join(self.dir, "张伟")
        EpisodicDistiller._save_checkpoint(sandbox, [f"h{i}" for i in range(25000)], None)
        with open(os.path.join(sandbox, "checkpoint.json"), encoding="utf-8") as f:
            hashes = json.load(f)["recorded_hashes"]
        self.assertEqual(len(hashes), 20000)
        self.assertEqual(hashes[-1], "h24999")
        self.assertEqual(hashes[0], "h5000")


if __name__ == "__main__":
    unittest.main()
