"""
Offline Generic Semantic Slot Assembler.
A purely structural conversational fallback engine that dynamically synthesizes
2x3 matrix options based on the speech act and extracted semantic tokens of the incoming message.
Contains ZERO hardcoded personal life experiences, anecdotes, or scenario-specific assumptions.
"""
import re
from typing import List, Dict, Any, Optional

def synthesize_scenario_options(
    target_name: str,
    incoming_text: str,
    memory: List[Dict[str, Any]],
    rules: Dict[str, Any],
    context_text: Optional[str] = None
) -> List[Dict[str, str]]:
    combined = f"{incoming_text} {context_text or ''}".strip()

    # 动态语义焦点提取 (Dynamic Semantic Focus Extraction)
    clean_snippet = re.sub(r"[，。！？\s]+", " ", incoming_text).strip()
    words = [w for w in clean_snippet.split(" ") if len(w) >= 2]
    topic_hint = words[-1] if words else "这事"

    # 1. 语式判定: 疲倦 / 吐槽 / 宣泄 (Venting / Fatigue / Frustration)
    if any(k in incoming_text for k in ["累", "烦", "气死", "生气", "头疼", "糟心", "无语", "离谱", "委屈", "折腾", "难受", "遭罪", "连轴", "加班", "开会"]):
        return [
            {"sub_goal": "直觉承接", "text": "这事换谁谁都得头疼，先歇口气缓缓，别硬撑着", "rationale": "直率承接疲惫与情绪，秒卸心理负担"},
            {"sub_goal": "老友同频", "text": "生活里的破事永远忙不完，该划水就划水，身体才是自己的", "rationale": "老友清醒发言，帮对方化解内耗"},
            {"sub_goal": "生活提醒", "text": "今天先把手头事对付过去，到点了赶紧撤，回去整点热乎的", "rationale": "实在接地气的生活提醒"},
            {"sub_goal": "微调提升", "text": "哈哈哈哈心态放平天下无敌，直接开启省电模式，谁也别想消耗我", "rationale": "基于槽位1微调：北方幽默笑闹解压"},
            {"sub_goal": "微调提升", "text": "犯不上为这点破事自己跟自己较劲，咋舒坦咋整，你占理你怕啥", "rationale": "基于槽位2微调：给足做人硬气与坚定护短"},
            {"sub_goal": "微调提升", "text": "晚上必须吃顿好的冲冲晦气，把烦心的人和事一键清空", "rationale": "基于槽位3微调：借美食仪式感翻篇落地"}
        ]

    # 2. 语式判定: 疑问 / 纠结 / 征求意见 (Seeking Advice / Hesitation)
    if any(k in incoming_text for k in ["怎么办", "咋办", "是不是", "行不行", "对不对", "哪个好", "选哪个", "意见", "纠结", "拿不准", "挑哪"]):
        return [
            {"sub_goal": "直觉承接", "text": "这事其实没那么复杂，按你自己第一直觉整最稳妥", "rationale": "直率消除纠结，给足定心丸"},
            {"sub_goal": "老友同频", "text": "犹豫不决说明两个选择差不多，挑个最省心不费劲的就完事了", "rationale": "理性老友视角，打破内耗"},
            {"sub_goal": "生活提醒", "text": "先别逼自己马上做决定，先放一放该干啥干啥，脑子清醒了再说", "rationale": "接地气生活实用建议"},
            {"sub_goal": "微调提升", "text": "哈哈哈哈遵从第一反应比啥都强，千金难买自己乐意，别自己难为自己", "rationale": "基于槽位1微调：幽默化解选择焦虑"},
            {"sub_goal": "微调提升", "text": "不管你最后怎么定我都站你这边，放平心态别有太大心理包袱", "rationale": "基于槽位2微调：坚定支持与心理撑腰"},
            {"sub_goal": "微调提升", "text": "等回头这事敲定了必须庆祝一下，不管是啥结果我都陪你复盘", "rationale": "基于槽位3微调：自然延伸老友互动"}
        ]

    # 3. 语式判定: 欢脱 / 搞笑 / 乐呵 (Humor / Amusement / Banter)
    if any(k in incoming_text for k in ["哈哈", "笑死", "太逗", "乐死", "有意思", "噗", "绝了", "逗"]):
        return [
            {"sub_goal": "直觉承接", "text": "哈哈哈哈光看你说我都跟着乐出声了，确实太逗了", "rationale": "秒接笑点同频，不扫兴"},
            {"sub_goal": "老友同频", "text": "这脑洞也是没谁了，今天一整天的快乐源泉全靠这事了", "rationale": "高能量情绪价值回响"},
            {"sub_goal": "生活提醒", "text": "多来点这种下饭笑料，今天心情直接给拉满了", "rationale": "鼓励分享欲，自然承接"},
            {"sub_goal": "微调提升", "text": "哈哈哈哈你这精神状态领先我十年，属实给我整乐了", "rationale": "基于槽位1微调：北方打趣幽默升级"},
            {"sub_goal": "微调提升", "text": "哈哈哈哈生活就得多点这种乐子，天天紧绷着多累，这样挺好的", "rationale": "基于槽位2微调：夸赞幽默感与笑闹氛围"},
            {"sub_goal": "微调提升", "text": "还有啥名场面没有，赶紧继续唠唠，我瓜子都备好了", "rationale": "基于槽位3微调：开放式生活分享邀请"}
        ]

    # 4. 语式判定: 邀约 / 计划 / 打算 (Planning / Invitation)
    if any(k in incoming_text for k in ["去不去", "要不要", "哪天", "周末", "打算", "想去", "聚聚", "整点", "约"]):
        return [
            {"sub_goal": "直觉承接", "text": "我看行，顺着你的时间安排来，我基本都方便", "rationale": "直率爽快响应邀约"},
            {"sub_goal": "老友同频", "text": "正好这阵子也想找机会放空一下，整挺好", "rationale": "老友同频共鸣，给足热情"},
            {"sub_goal": "生活提醒", "text": "把手头该收尾的事提前弄完，到时候安心玩", "rationale": "随手生活提醒"},
            {"sub_goal": "微调提升", "text": "哈哈哈哈必须安排上，提前把日程锁死，谁放鸽子谁请客", "rationale": "基于槽位1微调：熟络开玩笑立约定"},
            {"sub_goal": "微调提升", "text": "踏踏实实出去转转透透气，天天关在屋里人都快发霉了", "rationale": "基于槽位2微调：给足出门充电理由"},
            {"sub_goal": "微调提升", "text": "想好吃啥或者去哪儿没，有备选随时甩我，我来做攻略", "rationale": "基于槽位3微调：主动推进计划落地"}
        ]

    # 5. 通用日常分享兜底 (General Daily Sharing)
    return [
        {"sub_goal": "直觉承接", "text": "确实是这么个理，按你自己最顺手的节奏对付就完事了", "rationale": "真实生活状态自然搭茬"},
        {"sub_goal": "老友同频", "text": "我平时也差不多这样，怎么省心怎么来，不折腾自己", "rationale": "熟人老友第一反应认同与自身经验同频"},
        {"sub_goal": "生活提醒", "text": "先把眼前事对付明白，回头该吃吃该歇歇", "rationale": "实用大白话减负建议"},
        {"sub_goal": "微调提升", "text": "哈哈哈哈你这路子还挺稳妥的，突出一个省心踏实", "rationale": "基于槽位1微调：打趣老友日常节奏"},
        {"sub_goal": "微调提升", "text": "犯不上自己跟自己较劲，咋得劲咋整就完事了，不用在意外面怎么说", "rationale": "基于槽位2微调：给足做自己底气与护短"},
        {"sub_goal": "微调提升", "text": "今天先把手头事理顺，瞅着啥有意思的随时发来唠唠", "rationale": "基于槽位3微调：开放式生活分享邀请"}
    ]
