"""
Dynamic Term Search & Cognitive Boundary Calibration.
Searches encyclopedic/web knowledge for unfamiliar proper nouns and aligns
with Ego's real-world background to prevent hallucination and false expertise.
Contains ZERO hardcoded private personal data.
"""
import urllib.request
import urllib.parse
import json
import ssl
import re
from typing import List, Dict, Optional

_TERM_CACHE: Dict[str, Dict[str, str]] = {}

COMMON_STOPWORDS = {
    "今天", "明天", "昨天", "其实", "可以", "但是", "不过", "如果", "虽然",
    "因为", "所以", "这个", "那个", "怎么", "什么", "为什么", "我们", "你们",
    "他们", "一下", "一块", "一起", "很多", "觉得", "感觉", "知道", "看到",
    "也是", "就是", "还是", "或者", "没有", "有点", "真的", "非常", "特别",
    "大家", "这样", "那样", "这么", "那么", "然后", "之后", "之前", "地方",
    "东西", "事情", "说话", "吃饭", "睡觉", "路上", "回家", "上班", "开会",
    "消息", "时间", "时候", "现在", "刚才", "过去", "以后", "刚刚", "原来",
    "哈哈", "嘿嘿", "哎呀", "哇塞", "好的", "不错", "好看", "挺好", "喜欢",
    "差不多", "可能", "应该", "好像", "到底", "简直", "竟然", "赶紧", "已经",
    "还要", "准备", "正在", "打算", "居然", "真好看", "好累啊", "太累了", "开心",
    "最近", "平时", "当时", "后来", "整个人", "自己", "人家", "酸爽", "新入"
}

COMMON_SUFFIXES = [
    "手串", "手链", "项链", "耳钉", "戒指", "手镯", "面霜", "精华",
    "水乳", "眼霜", "防晒霜", "口红", "唇膏", "散粉", "香水", "外套",
    "大衣", "冲锋衣", "卫衣", "裤子", "鞋子", "球鞋", "包包", "双肩包",
    "耳机", "手表", "咖啡", "奶茶", "拿铁"
]

STOP_CHARS = set("的了个下在我你他这那一是有么嘛吧呢啊呀去来都就也还过很太真")

def _do_api_query(term: str) -> Optional[Dict[str, str]]:
    clean_term = term.strip()
    if not clean_term or len(clean_term) < 2 or clean_term in COMMON_STOPWORDS:
        return None
    if clean_term in _TERM_CACHE:
        return _TERM_CACHE[clean_term]

    ctx = ssl._create_unverified_context()

    # 1. 优先百度百科 API
    try:
        url = f"https://baike.baidu.com/api/openapi/BaikeLemmaCardApi?scope=103&format=json&appid=379020&bk_key={urllib.parse.quote(clean_term)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and (data.get("desc") or data.get("abstract")):
                res = {
                    "term": clean_term,
                    "title": data.get("title", clean_term),
                    "category": data.get("desc", ""),
                    "abstract": (data.get("abstract") or "")[:150]
                }
                _TERM_CACHE[clean_term] = res
                return res
    except Exception:
        pass

    # 2. 维基百科中文 API 兜底
    try:
        url = f"https://zh.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_term)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and data.get("extract"):
                res = {
                    "term": clean_term,
                    "title": data.get("title", clean_term),
                    "category": data.get("description", "相关事物"),
                    "abstract": data.get("extract", "")[:150]
                }
                _TERM_CACHE[clean_term] = res
                return res
    except Exception:
        pass

    return None

def lookup_term(term: str) -> Optional[Dict[str, str]]:
    """查询专有名词或概念的百科/网络事实概要 (智能去除常见通用物品后缀)"""
    clean_term = term.strip()
    if not clean_term or len(clean_term) < 2:
        return None

    # 先直接查
    res = _do_api_query(clean_term)
    if res:
        return res

    # 去除常见语法与品类后缀重试 (如 '黑曜石手串' -> '黑曜石', '海蓝之谜面霜' -> '海蓝之谜')
    clean_no_de = re.sub(r"^的|的$", "", clean_term)
    if clean_no_de != clean_term:
        res = _do_api_query(clean_no_de)
        if res:
            return res

    for suf in COMMON_SUFFIXES:
        if clean_no_de.endswith(suf) and len(clean_no_de) > len(suf):
            root = clean_no_de[:-len(suf)].rstrip("的")
            if len(root) >= 2:
                res = _do_api_query(root)
                if res:
                    return res

    return None

def extract_and_calibrate_terms(incoming_text: str, ego_profile: Optional[str] = None) -> List[Dict[str, str]]:
    """
    扫描待回复文本中的专有名词/品牌/生僻概念，检索知识并校准我方认知边界:
    返回格式: [{"term": ..., "category": ..., "abstract": ..., "cognitive_hint": ...}]
    """
    if not incoming_text or len(incoming_text) < 2:
        return []

    candidate_tokens: List[str] = []
    seen = set()

    def add_candidate(c: str):
        c = c.strip().strip("，。！？,.!? ")
        if c and len(c) >= 2 and c not in COMMON_STOPWORDS and c not in seen:
            seen.add(c)
            candidate_tokens.append(c)

    # 策略 1: 引号或书名号中的重点实体
    for m in re.finditer(r"[“\"「『《【]([^”\"」』》】]{2,12})[”\"」』》】]", incoming_text):
        add_candidate(m.group(1))

    # 策略 2: 动作动词紧跟的专有事物/品牌/产品
    action_pat = r"(?:试了下|试了试|试了|新入了个|新入了|入了个|入了件|入了套|入了双|入了|买了一瓶|买了个|买了件|买了套|买了双|买了|买个|喝了一杯|喝了杯|喝了个|喝了|吃了|用了|送了|穿了|戴了|尝了|点了一杯|点了杯|点了|在练|练了|去做了|做了|种草了一套|种草了|种草|安利了|安利|看了|听了|喷了|背了)([\u4e00-\u9fa5A-Za-z0-9]{2,10})"
    for m in re.finditer(action_pat, incoming_text):
        add_candidate(m.group(1))

    # 策略 3: 英文/数字复合词与品牌词 (如 AirPods, SK-II, Lululemon, 999 等)
    for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9\-\_\.]{1,20}", incoming_text):
        add_candidate(m.group(0))

    # 策略 4: 滑动 N-gram (长度 4 到 2)，排除高频虚词与助词
    clean_text = re.sub(r"[，。！？\s\n\.\,\!\?…~～]+", " ", incoming_text)
    for word in clean_text.split():
        if len(word) >= 2:
            for length in [4, 3, 2]:
                for i in range(len(word) - length + 1):
                    sub = word[i:i+length]
                    if not any(ch in STOP_CHARS for ch in sub) and sub not in COMMON_STOPWORDS:
                        add_candidate(sub)

    results = []
    matched_terms = set()
    # 限制探测前 6 个候选词，保证毫秒级响应
    for token in candidate_tokens[:6]:
        # 如果当前 token 已与已匹配成功的名词重合，跳过
        if any(token in m or m in token for m in matched_terms):
            continue

        term_info = lookup_term(token)
        if term_info and term_info.get("category"):
            hint = _calibrate_cognitive_boundary(term_info["category"], term_info.get("abstract", ""))
            results.append({
                "term": term_info["term"],
                "category": term_info["category"],
                "abstract": term_info["abstract"],
                "cognitive_hint": hint
            })
            matched_terms.add(term_info["term"])
            if len(results) >= 2:
                break

    return results

def _calibrate_cognitive_boundary(category: str, abstract: str) -> str:
    """根据概念所属门类，结合我方背景推断并校准我方的真实认知程度与回复原则"""
    corpus = f"{category} {abstract}"

    if any(k in corpus for k in ["化妆", "护肤", "口红", "粉底", "彩妆", "眼影", "防晒", "香水", "女装", "穿搭", "包包", "首饰", "奢侈品", "时尚", "珠宝", "配饰", "宝石", "矿石", "水晶", "玉石", "文玩"]):
        return (
            "【我方认知边界推断】：非擅长领域（真实北方男生平视视角）。大致知道是穿搭/护肤/饰品品类，但完全不知道细分成分、色号、玄学讲究或复杂工序。\n"
            "【回复铁律】：严禁编造任何虚假成分、工艺或技术参数！严禁装内行！从‘好看、显白、质感酷、显气质、省心、你开心就好’或幽默打趣切入，给足情绪价值。"
        )
    elif any(k in corpus for k in ["菜", "小吃", "食材", "餐饮", "饮品", "咖啡", "甜品", "美食", "糕点", "料理"]):
        return (
            "【我方认知边界推断】：接地气生活饮食视角。\n"
            "【回复铁律】：只关注‘好不好吃、过不过瘾、合不合胃口、随性聊口感’，绝对严禁生造虚假食材与配方！以真实烟火气回应。"
        )
    elif any(k in corpus for k in ["运动", "健身", "瑜伽", "普拉提", "跑步", "户外", "徒步", "露营", "骑行", "滑雪", "球类"]):
        return (
            "【我方认知边界推断】：生活与运动直男视角。\n"
            "【回复铁律】：知道大概是运动/户外项目，关注对方‘累不累、开不开心、帅不帅、过瘾不过瘾’，严禁假装资深教练指指点点！"
        )
    elif any(k in corpus for k in ["数码", "硬件", "电脑", "手机", "软件", "算法", "程序", "代码", "机械", "耳机"]):
        return (
            "【我方认知边界推断】：熟悉与本职领域（研发工程师视角）。\n"
            "【回复铁律】：懂原理但绝不在日常微信聊天中掉书袋或居高临下当理中客，大白话随性聊实用体验即可。"
        )
    else:
        return (
            "【我方认知边界推断】：日常平视未知见闻视角。\n"
            "【回复铁律】：知识库无记录，严禁凭空捏造事实！大方展现真实好奇、新鲜感或随性打趣，绝不假装全知全能。"
        )
