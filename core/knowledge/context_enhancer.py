"""
Context Enhancer: Temporal, Environmental, and Common-Sense Grounding.
Infers temporal features (workday/weekend/festivals/solar terms),
target special days (birthday/anniversary, if mentioned in records),
and target city/weather characteristics (if mentioned in records).
Strictly skips non-existent data without hallucinating.
Contains ZERO hardcoded private personal data.
"""
import os
import re
import ssl
import time
import json
import sqlite3
import datetime
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List

_WEATHER_CACHE: Dict[str, Dict[str, Any]] = {}

MAJOR_CITIES = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "武汉", "西安", "南京",
    "天津", "苏州", "郑州", "长沙", "沈阳", "青岛", "大连", "厦门", "昆明", "福州",
    "济南", "合肥", "哈尔滨", "长春", "南宁", "南昌", "贵阳", "海口", "乌鲁木齐", "兰州",
    "西宁", "银川", "呼和浩特", "东莞", "佛山", "无锡", "温州", "宁波", "珠海", "常州",
    "烟台", "唐山", "保定", "石家庄", "太原", "洛阳", "南通", "徐州", "潍坊", "临沂",
    "金华", "嘉兴", "绍兴", "泉州", "中山", "惠州", "江门", "汕头", "台州", "襄阳",
    "宜昌", "岳阳", "株洲", "衡阳", "芜湖", "柳州", "三亚", "桂林", "遵义", "大理",
    "丽江", "绵阳", "宜宾", "赣州", "九江", "景德镇", "威海", "淄博", "济宁", "开封"
]

CITY_PINYIN_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "重庆": "Chongqing", "武汉": "Wuhan",
    "西安": "Xian", "南京": "Nanjing", "天津": "Tianjin", "苏州": "Suzhou",
    "郑州": "Zhengzhou", "长沙": "Changsha", "沈阳": "Shenyang", "青岛": "Qingdao",
    "大连": "Dalian", "厦门": "Xiamen", "昆明": "Kunming", "福州": "Fuzhou",
    "济南": "Jinan", "合肥": "Hefei", "哈尔滨": "Harbin", "长春": "Changchun",
    "南宁": "Nanning", "南昌": "Nanchang", "贵阳": "Guiyang", "海口": "Haikou",
    "乌鲁木齐": "Urumqi", "兰州": "Lanzhou", "西宁": "Xining", "银川": "Yinchuan",
    "呼和浩特": "Hohhot", "东莞": "Dongguan", "佛山": "Foshan", "无锡": "Wuxi",
    "温州": "Wenzhou", "宁波": "Ningbo", "珠海": "Zhuhai", "常州": "Changzhou",
    "石家庄": "Shijiazhuang", "太原": "Taiyuan", "三亚": "Sanya", "大理": "Dali"
}

WEATHER_COND_MAP = {
    "sunny": "晴朗", "clear": "晴好", "partly cloudy": "多云", "cloudy": "多云",
    "overcast": "阴天", "smoky haze": "阴沉微霾", "haze": "有轻霾", "mist": "薄雾",
    "fog": "有雾", "patchy rain nearby": "局部阵雨", "light rain": "小雨",
    "moderate rain": "中雨", "heavy rain": "大雨", "light drizzle": "毛毛细雨",
    "thundery outbreaks nearby": "雷阵雨", "snow": "下雪", "sleet": "雨夹雪",
    "blizzard": "暴风雪", "windy": "大风"
}

SOLAR_TERMS_REF = [
    ((1, 5, 1, 7), "小寒", "隆冬严寒"),
    ((1, 20, 1, 22), "大寒", "岁末深冬"),
    ((2, 3, 2, 5), "立春", "初春回暖"),
    ((2, 18, 2, 20), "雨水", "春雨初生"),
    ((3, 5, 3, 7), "惊蛰", "春雷惊蛰"),
    ((3, 20, 3, 22), "春分", "春意盎然"),
    ((4, 4, 4, 6), "清明", "清明春深"),
    ((4, 19, 4, 21), "谷雨", "暮春谷雨"),
    ((5, 5, 5, 7), "立夏", "初夏渐热"),
    ((5, 20, 5, 22), "小满", "夏意渐浓"),
    ((6, 5, 6, 7), "芒种", "仲夏芒种"),
    ((6, 21, 6, 22), "夏至", "炎炎夏日"),
    ((7, 6, 7, 8), "小暑", "小暑盛夏"),
    ((7, 22, 7, 24), "大暑", "大暑酷热"),
    ((8, 7, 8, 9), "立秋", "立秋初凉"),
    ((8, 22, 8, 24), "处暑", "处暑渐凉"),
    ((9, 7, 9, 9), "白露", "白露微凉"),
    ((9, 22, 9, 24), "秋分", "秋分气爽"),
    ((10, 8, 10, 9), "寒露", "寒露秋意浓"),
    ((10, 23, 10, 24), "霜降", "霜降深秋"),
    ((11, 7, 11, 8), "立冬", "立冬初寒"),
    ((11, 22, 11, 23), "小雪", "小雪初冬"),
    ((12, 6, 12, 8), "大雪", "大雪严冬"),
    ((12, 21, 12, 23), "冬至", "冬至数九")
]

PUBLIC_FESTIVALS = {
    (1, 1): "元旦",
    (2, 14): "情人节",
    (3, 8): "国际妇女节 (女神节)",
    (4, 1): "愚人节",
    (5, 1): "五一劳动节",
    (5, 4): "五四青年节",
    (5, 20): "520 网络情人节",
    (5, 21): "521",
    (6, 1): "儿童节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
    (10, 31): "万圣夜",
    (11, 1): "万圣节",
    (11, 11): "双十一购物节",
    (12, 24): "平安夜",
    (12, 25): "圣诞节",
    (12, 31): "跨年夜"
}

def get_temporal_context(now: Optional[datetime.datetime] = None) -> Dict[str, str]:
    """生成今日日期的常识特征（星期、工作日/周末、时段、节令、假期节点）"""
    if now is None:
        now = datetime.datetime.now()

    year, month, day = now.year, now.month, now.day
    hour = now.hour
    weekday_idx = now.weekday()

    weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_str = weekdays_cn[weekday_idx]

    # 工作日/周末属性
    if weekday_idx == 4:
        day_type = "工作日 (周五临近周末，心态期待松弛)"
    elif weekday_idx in (5, 6):
        day_type = "周末公休日 (休闲放松生活节奏)"
    elif weekday_idx == 0:
        day_type = "工作日 (周一开工，日常打工搬砖)"
    else:
        day_type = "工作日 (周中正常搬砖作息)"

    # 一天中的时段属性
    if 6 <= hour < 9:
        time_slot = "早晨 (上班通勤 / 刚起床 / 早餐)"
    elif 9 <= hour < 11:
        time_slot = "上午 (工作处理 / 搬砖 / 会议)"
    elif 11 <= hour < 14:
        time_slot = "中午 (午饭 / 午休消食)"
    elif 14 <= hour < 17:
        time_slot = "下午 (工作冲刺 / 下午茶 / 犯困摸鱼)"
    elif 17 <= hour < 19:
        time_slot = "傍晚 (下班通勤 / 晚饭路上)"
    elif 19 <= hour < 22:
        time_slot = "晚间 (黄金休闲 / 追剧 / 聊天高频)"
    elif 22 <= hour or hour < 2:
        time_slot = "深夜 (睡前放松 / 夜猫子时段)"
    else:
        time_slot = "凌晨 (深度睡眠 / 极端夜猫子)"

    # 节日与长假/收假特征
    festivals = []
    if (month, day) in PUBLIC_FESTIVALS:
        festivals.append(PUBLIC_FESTIVALS[(month, day)])
    
    # 国庆假期及收假窗口
    if month == 10 and 1 <= day <= 7:
        festivals.append("十一国庆长假期间")
    elif month == 10 and 8 <= day <= 10:
        festivals.append("国庆长假刚收假返工首周（打工人节后适应期）")
    elif month == 5 and 1 <= day <= 5:
        festivals.append("五一小长假期间")
    elif month == 5 and 6 <= day <= 7:
        festivals.append("五一节后开工适应期")

    # 节气推断 (当天或前后1~2天内)
    term_name = ""
    for (sm, sd, em, ed), tname, tdesc in SOLAR_TERMS_REF:
        if (month == sm and sd <= day) or (month == em and day <= ed):
            term_name = f"{tname} ({tdesc})"
            break

    node_desc = ""
    if festivals:
        node_desc += "、".join(festivals)
    if term_name:
        node_desc = f"{node_desc} · {term_name}" if node_desc else term_name
    if not node_desc:
        node_desc = "常规生活时序"

    return {
        "date_str": f"{year}年{month}月{day}日 {weekday_str}",
        "day_type": day_type,
        "time_slot": time_slot,
        "festival_and_term": node_desc
    }

def infer_special_days(target_name: str, contacts_dir: str, now: Optional[datetime.datetime] = None) -> Optional[str]:
    """
    根据历史对话与档案推断对方是否是生日或双方纪念日。
    如果往常对话没体现，坚决返回 None（跳过，绝不瞎编）。
    """
    if now is None:
        now = datetime.datetime.now()

    target_dir = os.path.join(contacts_dir, target_name)
    if not os.path.exists(target_dir):
        return None

    corpus_lines = []
    dossier_path = os.path.join(target_dir, "dossier.md")
    if os.path.exists(dossier_path):
        try:
            with open(dossier_path, "r", encoding="utf-8") as f:
                corpus_lines.extend(f.readlines())
        except Exception:
            pass

    db_path = os.path.join(target_dir, "index.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT facts_summary FROM episode_records WHERE facts_summary LIKE '%生日%' OR facts_summary LIKE '%出生%' OR facts_summary LIKE '%纪念日%' LIMIT 10")
            for r in cur.fetchall():
                corpus_lines.append(r[0])
            conn.close()
        except Exception:
            pass

    corpus = " ".join(corpus_lines)
    if not corpus or ("生日" not in corpus and "出生" not in corpus and "纪念日" not in corpus and "在一起" not in corpus):
        return None

    # 正则提取生日: 覆盖多种前后置语序
    bday_matches = re.findall(r'(?:生日|出生|生于|诞辰)(?:是|在|为|：|:|\s)*([0-9]{1,4}[-年/\.])?([0-9]{1,2})[-月/\.]([0-9]{1,2})', corpus)
    if not bday_matches:
        bday_rev = re.findall(r'([0-9]{1,2})[-月/\.]([0-9]{1,2})[日号]?\s*(?:生日|出生|生于|过生|过生日)', corpus)
        if bday_rev:
            bday_matches = [("", m[0], m[1]) for m in bday_rev]

    for m in bday_matches:
        try:
            bm = int(m[1])
            bd = int(m[2])
            if bm == now.month and bd == now.day:
                return f"【今日特殊节点】：今天是对方生日（{bm}月{bd}日）！可适度在聊天中给予真诚温暖的生日祝福或准备小惊喜、请客等话题。"
            
            # 判断临近（未来 1~3 天内）
            target_date = datetime.date(now.year, bm, bd)
            curr_date = now.date()
            days_diff = (target_date - curr_date).days
            if 1 <= days_diff <= 3:
                return f"【近期特殊节点预警】：对方生日临近（{bm}月{bd}日，距今还剩 {days_diff} 天），可留意是否提到庆祝安排。"
        except Exception:
            pass

    # 正则提取纪念日
    anni_matches = re.findall(r'(?:纪念日|相识|在一起|认识|周年)(?:是|在|为|：|:|\s)*([0-9]{1,4}[-年/\.])?([0-9]{1,2})[-月/\.]([0-9]{1,2})', corpus)
    if not anni_matches:
        anni_rev = re.findall(r'([0-9]{1,2})[-月/\.]([0-9]{1,2})[日号]?\s*(?:纪念日|在一起|周年)', corpus)
        if anni_rev:
            anni_matches = [("", m[0], m[1]) for m in anni_rev]

    for m in anni_matches:
        try:
            am = int(m[1])
            ad = int(m[2])
            if am == now.month and ad == now.day:
                return f"【今日特殊节点】：今天是双方特别纪念日（{am}月{ad}日），交流时可带出相关默契或回忆。"
        except Exception:
            pass

    return None

def infer_city_and_weather(target_name: str, contacts_dir: str) -> Optional[str]:
    """
    根据历史记录推断对方常住城市与今日天气。
    如果往常对话没体现对方城市，坚决返回 None（跳过，绝不瞎编）。
    """
    target_dir = os.path.join(contacts_dir, target_name)
    if not os.path.exists(target_dir):
        return None

    corpus_lines = []
    dossier_path = os.path.join(target_dir, "dossier.md")
    if os.path.exists(dossier_path):
        try:
            with open(dossier_path, "r", encoding="utf-8") as f:
                corpus_lines.extend(f.readlines())
        except Exception:
            pass

    # 优先从 dossier 显式字段提取常住地/城市
    inferred_city = None
    for line in corpus_lines:
        if any(k in line for k in ["常住", "城市", "所在地", "现居", "坐标", "工作地"]):
            for c in MAJOR_CITIES:
                if c in line:
                    inferred_city = c
                    break
        if inferred_city:
            break

    # 若 dossier 无显式字段，检查历史记录的高频城市
    if not inferred_city:
        db_path = os.path.join(target_dir, "index.db")
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute("SELECT facts_summary FROM episode_records ORDER BY id DESC LIMIT 30")
                facts_text = " ".join([r[0] for r in cur.fetchall()])
                conn.close()
                for c in MAJOR_CITIES:
                    # 匹配强上下文关联，如 "在上海", "回北京", "深圳的家"
                    if re.search(rf"(?:在|去|回|住|生活在|呆在){c}", facts_text):
                        inferred_city = c
                        break
            except Exception:
                pass

    if not inferred_city:
        return None

    # 获取天气
    weather_desc = _get_city_weather(inferred_city)
    if weather_desc:
        return f"【对方城市与天气参考】：推断常住/位于【{inferred_city}】，今日天气：{weather_desc}（供生活常识参考，可随性融入下雨/添衣/温差等自然关怀，无需生硬提及）。"
    else:
        return f"【对方城市参考】：推断常住/位于【{inferred_city}】。"

def _get_city_weather(city_cn: str) -> Optional[str]:
    """查询指定城市的实时天气概要 (带 30 分钟内存缓存与 2.0s 熔断保护)"""
    now_ts = time.time()
    if city_cn in _WEATHER_CACHE:
        cached = _WEATHER_CACHE[city_cn]
        if now_ts - cached["ts"] < 1800:
            return cached["desc"]

    pinyin = CITY_PINYIN_MAP.get(city_cn, city_cn)
    ctx = ssl._create_unverified_context()
    url = f"https://wttr.in/{urllib.parse.quote(pinyin)}?format=%C+%t"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=1.0) as resp:
            text = resp.read().decode("utf-8").strip()
            # 解析例如 'Smoky haze +20°C'
            m = re.match(r"^([A-Za-z\s]+)\s+([+\-0-9°C]+)$", text)
            if m:
                raw_cond = m.group(1).strip().lower()
                temp = m.group(2).strip()
                cond_cn = WEATHER_COND_MAP.get(raw_cond, raw_cond)
                desc = f"{cond_cn} {temp}"
            else:
                desc = text

            _WEATHER_CACHE[city_cn] = {"ts": now_ts, "desc": desc}
            return desc
    except Exception:
        _WEATHER_CACHE[city_cn] = {"ts": now_ts, "desc": None}
        pass

    return None

def build_environmental_context(target_name: str, contacts_dir: str, now: Optional[datetime.datetime] = None) -> str:
    """整合时空常识、专属特殊日子（若有）与对方城市天气（若有），生成紧凑提示块"""
    temporal = get_temporal_context(now)
    special_day = infer_special_days(target_name, contacts_dir, now)
    city_weather = infer_city_and_weather(target_name, contacts_dir)

    lines = [
        f"- 今日时序节点: {temporal['date_str']} | {temporal['day_type']} | {temporal['time_slot']}",
        f"- 节令与假期特征: {temporal['festival_and_term']}"
    ]

    if special_day:
        lines.append(f"- {special_day}")

    if city_weather:
        lines.append(f"- {city_weather}")

    return "【今日时空常识与环境背景 (供大白话日常聊天同频参考，严禁机械背诵)】:\n" + "\n".join(lines) + "\n\n"
