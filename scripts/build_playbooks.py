#!/usr/bin/env python3
"""
Compile and distill 31 communication guides into structured situational micro-playbooks (knowledge/playbooks.json).
"""
import os
import json

PLAYBOOKS = [
    # === EMOTIONAL (4) ===
    {
        "id": "emotional_praise_appreciation",
        "category": "emotional",
        "source_doc": "万能夸人的话术技巧：真诚认可的实用指南.md",
        "title": "细节看见与品味赞许",
        "triggers": ["好看", "漂亮", "新买", "新做", "自拍", "穿搭", "发型", "指甲", "首饰", "口红", "试了", "看我", "做好了", "蛋糕", "手艺", "画的", "新衣服", "项链", "鞋子"],
        "taboo": "严禁假大空敷衍套话（如'还行吧','凑合','挺好的'），严禁扫兴挑刺（如'这有啥用','挺贵的吧','容易脏'）",
        "principle": "夸具体细节与审美眼光，不假大空；顺着对方的小得意肯定其品味，给足被真诚欣赏与被重视的正向反馈",
        "tactics": "抓取具体视觉或体验细节（质感/眼光/反差）；肯定对方审美有眼光；好奇打听购买或制作过程，激发倾诉欲"
    },
    {
        "id": "emotional_value_support",
        "category": "emotional",
        "source_doc": "为他人提供情绪价值：温暖且有效的回应指南.md",
        "title": "情绪共情与无条件偏袒撑腰",
        "triggers": ["烦", "累", "骂", "委屈", "难受", "崩溃", "伤心", "倒霉", "不爽", "无语", "气死", "焦虑", "失眠", "郁闷", "加班", "头疼", "生病", "太难了", "心累", "好烦啊"],
        "taboo": "绝对严禁长辈式说教、理性分析谁对谁错（严禁'你也有问题','多喝热水','早点睡'或客观纠错）",
        "principle": "情绪大于事实，无条件站在对方立场共情撑腰；做情绪的容器，同仇敌忾，先接住感受再聊其他",
        "tactics": "情绪命名与同盟撑腰（'这确实过分了','换我也得炸'）；无条件偏袒消除自我怀疑；递杯虚拟奶茶或暖心陪伴"
    },
    {
        "id": "emotional_presence_confidence",
        "category": "emotional",
        "source_doc": "提高气场：从内到外的力量感塑造指南.md",
        "title": "松弛定力与心理托底",
        "triggers": ["紧张", "怯场", "怕", "怂", "不敢", "心虚", "露馅", "怎么办", "没底气", "不知道咋整"],
        "taboo": "严禁否定自责，严禁把紧张伪装成傲慢或硬撑",
        "principle": "松弛感源于允许自己不完美；稳住呼吸与节奏，平视所有人，不讨好不防御",
        "tactics": "肯定真实面对的勇气；幽默自嘲卸掉光环包袱；给足心理托底（'有我在呢','天塌不下来'）"
    },
    {
        "id": "emotional_connection_overcome_isolation",
        "category": "emotional",
        "source_doc": "被孤立如何破局：从自我调适到建立连接的实用指南.md",
        "title": "自主归属与微观温暖",
        "triggers": ["格格不入", "融不进去", "没人理", "被排挤", "被孤立", "孤单", "一个人", "不想社交"],
        "taboo": "严禁强求融入不属于自己的圈子，严禁陷入自我攻击",
        "principle": "高质量的独处胜过低质量的合群；把能量收回自身，从一对一真实同频的微小连接开始",
        "tactics": "接纳并安抚被冷落的难受；肯定独立自我的独特价值；建立低压力、一对一的真实关怀"
    },

    # === DYNAMIC (7) ===
    {
        "id": "dynamic_dating_initiation",
        "category": "dynamic",
        "source_doc": "吸引约会与关系启动指南.md",
        "title": "种草埋点与低压力模糊邀约",
        "triggers": ["好感", "心动", "喜欢", "约会", "见面", "线下", "看电影", "吃饭", "喝一杯", "拔草", "新开的", "去玩", "放假", "周末"],
        "taboo": "严禁查户口式盘问，严禁高压紧逼式表白（严禁'你到底对我啥感觉','做我女朋友吧'）",
        "principle": "吸引力来自轻松、有趣与独特的相互契合；用模糊邀约测试意向，逐步建立线下交集",
        "tactics": "顺着共同喜好种草；抛出低压力模糊邀约（'下次有空去拔草'）；留下台阶与弹性空间"
    },
    {
        "id": "dynamic_natural_expression_first_meet",
        "category": "dynamic",
        "source_doc": "主动表达、第一次见面与自然接触.md",
        "title": "初见破冰与平视融洽",
        "triggers": ["第一次见", "初见", "碰头", "到了", "你在哪", "见面", "穿什么", "认出来"],
        "taboo": "严禁端着架子面试对方，严禁过于拘谨客套",
        "principle": "用生活化、真实的生活切片打开局面；把对方当成认识很久的老友，眼神温和，姿态开放",
        "tactics": "调侃初见的紧张感化解严肃；赞赏对方容易辨识的细节；主动引导接下来的轻松行程"
    },
    {
        "id": "dynamic_wechat_rhythm_topic_extension",
        "category": "dynamic",
        "source_doc": "线上微信聊天的节奏把控与话题延伸指南.md",
        "title": "状态陈述+细节共鸣与节奏调谐",
        "triggers": ["在吗", "在干嘛", "忙吗", "睡了没", "吃饭了吗", "今天怎么样", "刚下班", "回家了", "摸鱼"],
        "taboo": "严禁'嗯/哦/好'单字把天聊死，严禁查户口式连续追问",
        "principle": "陈述事实+分享感受+轻留话口；保持能量相当的字数和回复节奏，不秒回窒息也不故意冷落",
        "tactics": "状态陈述带出生活画面感；抛出开放式小问号；埋下下次互动的钩子"
    },
    {
        "id": "dynamic_natural_flow_inner_state",
        "category": "dynamic",
        "source_doc": "自然流、内在状态与结构化互动.md",
        "title": "内在稳定与场景自然流淌",
        "triggers": ["不知道说啥", "卡壳", "冷场", "话题", "没话找话", "无聊", "发呆"],
        "taboo": "严禁机械套用网恋模板，严禁为了制造人设而撒谎",
        "principle": "真实就是最强大的磁场；卸下防御，关注当下环境中的微小趣味，顺水推舟",
        "tactics": "从眼前的琐碎细节聊起（天气/食物/路况）；用真诚的感受取代精心设计的段子；允许短暂沉默"
    },
    {
        "id": "dynamic_scene_calibration_advance",
        "category": "dynamic",
        "source_doc": "场景感、松弛感与社交校准：从接话到关系推进.md",
        "title": "场景松弛与体感校准推进",
        "triggers": ["怎么接", "接不住", "这啥意思", "该怎么说", "推进", "下一步"],
        "taboo": "严禁越级推进关系，严禁对方客气当真爱、对方冷淡硬撩",
        "principle": "根据对方当前的兴趣窗口校准体感温度；对方热情则顺势升温，对方收敛则及时撤退",
        "tactics": "识别对方的温度信号；给予同频或微高于对方的热情反馈；保持进退自如的体面"
    },
    {
        "id": "dynamic_passive_to_active",
        "category": "dynamic",
        "source_doc": "聊天化被动为主动：引导互动的实用指南.md",
        "title": "二选一决策与轻快控场",
        "triggers": ["哦", "好吧", "还行", "随便", "都行", "你定", "不知道"],
        "taboo": "严禁把'随便'当成敷衍去生气怼对方，严禁放弃主导权僵住",
        "principle": "化被动为主动的钥匙在于提供清晰的二选一选项，减轻对方决策负担",
        "tactics": "幽默化解敷衍（'看来这是把决策权全交给我了'）；给出明确的A/B二选一选项；主动拍板担当"
    },
    {
        "id": "dynamic_networking_connection",
        "category": "dynamic",
        "source_doc": "有效拓展人脉：从建立到维护的实用指南.md",
        "title": "互惠利他与清晰边界连接",
        "triggers": ["认识一下", "交个朋友", "合作", "资源", "请教", "加个微信", "大佬"],
        "taboo": "严禁卑微讨好，严禁毫无价值支撑的无效社交",
        "principle": "人脉的本质是互惠与同频；带着利他视角与清晰边界，真诚表达欣赏与合作空间",
        "tactics": "肯定对方具体成就或观点；简明阐述自己的背景与互补价值；提出极低门槛的交流切入点"
    },

    # === TACTICS (8) ===
    {
        "id": "tactics_awkwardness_salvage",
        "category": "tactics",
        "source_doc": "化解尴尬：轻松救场的实用指南.md",
        "title": "自嘲化解与顺水推舟救场",
        "triggers": ["尴尬", "手滑", "发错", "卡住", "撤回", "忘回", "不好意思", "抱歉", "没看到", "出丑", "翻车"],
        "taboo": "严禁反复道歉加重尴尬，严禁假装没发生沉默冷场，严禁甩锅他人",
        "principle": "尴尬的核心是沟通张力失衡；通过幽默自嘲、顺水推舟或大度给台阶卸掉严肃感",
        "tactics": "幽默自嘲抢先开玩笑（'只要我不尴尬，尴尬的就是空气'）；迅速把话题自然引向好玩的点；给足对方面子和台阶"
    },
    {
        "id": "tactics_humor_banter",
        "category": "tactics",
        "source_doc": "幽默接梗与曲解调侃：打破冷场的高情商指南.md",
        "title": "幽默接梗与善意曲解",
        "triggers": ["哈哈", "逗", "损", "笑死", "调皮", "坏", "扯", "算了吧", "才不", "才怪", "找打", "哼", "略略略"],
        "taboo": "严禁油腻套路语录，严禁人身攻击、外貌挑刺或刻薄冷嘲热讽",
        "principle": "把严肃的事情变轻快，善意曲解、反差自嘲与角色互换；平视捧哏，会护短逗乐",
        "tactics": "善意曲解对方的娇嗔或打趣；建立两人的同盟秘密；用生动反差的画面感逗乐对方"
    },
    {
        "id": "tactics_clever_responses",
        "category": "tactics",
        "source_doc": "巧妙接话技巧：让沟通更流畅的实用指南.md",
        "title": "情绪借力与反向抛球",
        "triggers": ["是吗", "真假", "真的假的", "怎么会", "不信", "你猜", "你觉得呢", "咋办"],
        "taboo": "严禁较真辩论，严禁机械回答'真的','确实'",
        "principle": "不就事论事地平铺直叙，而是接住话背后的互动情绪，借力打力",
        "tactics": "顺应对方的话往上抬一层；反向抛球给对方；带点自信小打趣或宠溺"
    },
    {
        "id": "tactics_nonsense_banter",
        "category": "tactics",
        "source_doc": "废话文学回复指南：轻松应对各类场景.md",
        "title": "生活碎语同频与烟火气回响",
        "triggers": ["困了", "饿了", "冷", "热", "今天好累", "周五了", "下雨了", "无聊啊"],
        "taboo": "严禁长篇大论讲废话常识（'冷就穿衣','饿就吃饭'），严禁冷漠忽略",
        "principle": "废话是感情的润滑剂；把无意义的日常琐事回应得生动有趣、充满烟火气",
        "tactics": "同频呼应身体感受；顺着无聊延展出好玩脑洞；制造随时在身边的陪伴感"
    },
    {
        "id": "tactics_asking_favors",
        "category": "tactics",
        "source_doc": "托人办事的高效话术指南.md",
        "title": "认可铺垫与低负担委托",
        "triggers": ["帮个忙", "能不能帮我", "麻烦你", "求助", "拜托", "有空吗"],
        "taboo": "严禁上来就直接扔需求不管对方在干嘛，严禁道德绑架式强求",
        "principle": "先铺垫情绪与尊重，给足拒绝的台阶，事后闭环反馈与感恩回馈",
        "tactics": "认可对方的专业与能力；清楚交代事情范围与轻量要求；给足退路并表达谢意"
    },
    {
        "id": "tactics_logical_expression",
        "category": "tactics",
        "source_doc": "提升表达逻辑性：从混乱到清晰的实用指南.md",
        "title": "结论先行与结构化短句",
        "triggers": ["没说明白", "乱", "听不懂", "啥意思", "核心是啥", "说重点"],
        "taboo": "严禁东拉西扯、毫无主谓宾的长篇语音或文字轰炸",
        "principle": "结论先行，分层陈述，用结构化短句传递清晰信息",
        "tactics": "先说一句话核心；拆解为1、2点事实；给出清晰明确的行动建议"
    },
    {
        "id": "tactics_branching_orchestrator",
        "category": "tactics",
        "source_doc": "实战话术编排器：从一句回复到后续分支.md",
        "title": "双向出口与多维分支引导",
        "triggers": ["怎么聊下去", "后续", "然后呢", "接着说", "聊什么"],
        "taboo": "严禁单线死磕同一个枯竭话题",
        "principle": "一句话留两个出口：一个就事论事，一个延展到生活或情感体验",
        "tactics": "提供承接支点；埋下分支线索；观察对方选择并顺势深入"
    },
    {
        "id": "tactics_rehearsal_cards",
        "category": "tactics",
        "source_doc": "实用对话情境与演练卡.md",
        "title": "情境快照与即兴对齐",
        "triggers": ["情境", "模拟", "对练", "实战", "演练"],
        "taboo": "严禁死记硬背标准答案",
        "principle": "掌握不变的底层沟通逻辑，在实战中灵活组合语料",
        "tactics": "快速定位场景特征；调取适配的情感与语言频段；随机应变"
    },

    # === BOUNDARY (7) ===
    {
        "id": "boundary_high_eq_refusal",
        "category": "boundary",
        "source_doc": "高情商拒绝他人：体面护边界的实用指南.md",
        "title": "体面护界与温和坚定拒绝",
        "triggers": ["不想去", "不想借", "拒绝", "不太想", "算了吧", "改天吧", "压力大", "别问了", "抱歉不能"],
        "taboo": "严禁模糊敷衍吊胃口，严禁生硬冰冷伤感情，严禁过度道歉自我否定",
        "principle": "温和而坚定；肯定对方的情谊，清晰表达自己的局限与边界，必要时给替代方案",
        "tactics": "感谢邀请或认可；坦诚告知客观阻碍（时间/精力/原则）；祝愿顺利或提出改天聚"
    },
    {
        "id": "boundary_conflict_deescalation",
        "category": "boundary",
        "source_doc": "沟通冲突拆解与修复指南.md",
        "title": "降温倾听与情绪解绑修复",
        "triggers": ["生气了", "吵架", "不理我", "拉黑", "冷战", "别说了", "烦死你", "讨厌你", "绝交"],
        "taboo": "严禁冷战逃避，严禁翻旧账攻击人格，严禁强辩论输赢",
        "principle": "先处理情绪，再处理事实；冲突的本质是未被听见的渴望与受伤",
        "tactics": "暂停争论，先接纳对方的愤怒；承认自己表达不当的地方；表达在乎与修复诚意"
    },
    {
        "id": "boundary_rational_dispute",
        "category": "boundary",
        "source_doc": "万能吵架技巧：理性冲突处理指南.md",
        "title": "非暴力表达与事实聚焦",
        "triggers": ["讲道理", "凭什么", "不公平", "你凭啥", "少来这套", "辩论", "较真"],
        "taboo": "严禁使用'你总是','你每次都'绝对化否定词，严禁人身攻击",
        "principle": "对事不对人；用'我感受'代替'你做错'，聚焦解决方案而非发泄怨气",
        "tactics": "描述客观发生的事实；表达自己的主观感受；提出具体的期待改进方式"
    },
    {
        "id": "boundary_intimate_respect",
        "category": "boundary",
        "source_doc": "亲密互动与尊重边界指南.md",
        "title": "边界敬畏与知情同意互动",
        "triggers": ["越界", "太快了", "尴尬", "别动", "离远点", "慢一点", "吓到我"],
        "taboo": "严禁强行推进肢体接触，严禁把对方的犹豫当成欲擒故纵",
        "principle": "任何亲密都必须建立在知情同意与双向舒适之上；尊重边界才是最大吸引力",
        "tactics": "立即退回安全距离；坦诚道歉并安抚受惊情绪；明确尊重对方节奏"
    },
    {
        "id": "boundary_downgrade_repair",
        "category": "boundary",
        "source_doc": "关系降级、背叛与修复指南.md",
        "title": "体面降级与透明重建信任",
        "triggers": ["做朋友吧", "分手", "回不去了", "欺骗", "隐瞒", "信任没了", "算了吧"],
        "taboo": "严禁死缠烂打、威逼利诱，严禁假装一切没发生",
        "principle": "信任崩塌无法一蹴而就修复；接受关系的自然降级，用长期的言行一致重建安全感",
        "tactics": "体面接受现实，克制纠缠；深刻复盘并真诚致歉；给予彼此疗愈空间"
    },
    {
        "id": "boundary_manipulation_defense",
        "category": "boundary",
        "source_doc": "识别套路操控与健康替代指南.md",
        "title": "现实检验与主体性觉醒",
        "triggers": ["PUA", "套路", "内疚", "打压", "忽冷忽热", "断崖式", "精神控制", "怪我"],
        "taboo": "严禁陷入自我怀疑和内耗，严禁试图改变操控者",
        "principle": "识别煤气灯效应；建立清晰的现实检验，牢牢守住自我评价的主导权",
        "tactics": "坚定自我价值感；用事实戳破模糊的指责；果断设立不可退让的底线"
    },
    {
        "id": "boundary_reciprocity_balance",
        "category": "boundary",
        "source_doc": "关系投入失衡：互惠判断、降级投入与退出决策.md",
        "title": "互惠校准与止损决策",
        "triggers": ["好累", "剃头挑子一头热", "总是主动", "不回消息", "付出了好多", "没回应", "值得吗"],
        "taboo": "严禁加倍讨好试图换取回应，严禁怨气冲天地索取回报",
        "principle": "健康的爱是双向奔赴；当发现投入严重失衡且沟通无果时，体面降低投入甚至果断止损",
        "tactics": "暂停单向过度付出；将注意力拉回自己的生活与成长；观察对方反应再做决策"
    },

    # === PSYCHOLOGY (5) ===
    {
        "id": "psychology_attachment_regulation",
        "category": "psychology",
        "source_doc": "依恋理论与情绪调节指南.md",
        "title": "依恋安全感与弹性距离调节",
        "triggers": ["安全感", "患得患失", "害怕失去", "粘人", "逃避", "冷漠", "推开", "焦虑"],
        "taboo": "严禁指责焦虑型粘人，严禁追着回避型步步紧逼",
        "principle": "理解不同依恋风格的深层恐惧；用稳定的陪伴安抚焦虑，用给足空间温暖回避",
        "tactics": "给予可预期的确定性回应；尊重对方的独处与冷却需求；建立安全依恋基础"
    },
    {
        "id": "psychology_mbti_matching",
        "category": "psychology",
        "source_doc": "MBTI人格特质与沟通匹配指南.md",
        "title": "认知功能理解与同频共振",
        "triggers": ["MBTI", "INFP", "ENFP", "INTJ", "ENTP", "ISTJ", "ISFP", "E人", "I人", "J人", "P人", "人格", "测试"],
        "taboo": "严禁刻板印象贴标签否定人，严禁机械对照教条",
        "principle": "理解不同认知功能在信息输入与决策上的差异；对I人留空间，对E人给反应，对T人讲事实，对F人给共鸣",
        "tactics": "调侃MBTI切入；顺应对方的认知习惯；挖掘反差萌"
    },
    {
        "id": "psychology_intimate_theory",
        "category": "psychology",
        "source_doc": "亲密关系心理学总论.md",
        "title": "情感账户存储与共同成长",
        "triggers": ["亲密关系", "爱情", "长久", "磨合", "三观", "合适", "依赖", "伴侣"],
        "taboo": "严禁追求完美无瑕的童话恋爱，严禁把差异当成无法逾越的鸿沟",
        "principle": "亲密关系是共同成长的容器；用包容接纳彼此的不完美，在日常互动中积累情感账户存款",
        "tactics": "积极肯定对方的微小付出；在日常中创造属于两个人的专属仪式感；共同面对未知"
    },
    {
        "id": "psychology_digital_social_mindset",
        "category": "psychology",
        "source_doc": "在线约会与数字社交心智.md",
        "title": "去滤镜化与数字钝感力",
        "triggers": ["网聊", "社交软件", "划一划", "头像", "朋友圈", "仅三天可见", "点赞", "互动"],
        "taboo": "严禁隔着屏幕脑补对方完美人设，严禁将未读不回当成人格否定",
        "principle": "数字屏幕只是入口，真实线下才是归宿；去神秘化，保持平常心与适度钝感力",
        "tactics": "从朋友圈或动态细节寻找自然话题；保持轻松友善的互动频次；适时过渡到真实生活交流"
    },
    {
        "id": "psychology_interaction_calibration",
        "category": "psychology",
        "source_doc": "经典社交互动机制与认知校准.md",
        "title": "同理观察与真实利他回响",
        "triggers": ["读心术", "冷读", "套路", "看透", "真诚", "机制", "心智", "校准"],
        "taboo": "严禁使用欺骗性冷读伎俩，严禁迷信速成PUA套路",
        "principle": "最高级的技巧是基于同理心的敏锐观察与真诚利他；穿透表象，看见对方真实的渴望",
        "tactics": "观察对方细微的言语喜好；给出真诚不敷衍的独特回响；始终保持知行合一"
    }
]

def main():
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "knowledge"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "playbooks.json")
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(PLAYBOOKS, f, ensure_ascii=False, indent=2)
    
    print(f"Successfully compiled {len(PLAYBOOKS)} situational micro-playbooks into {out_path}")

if __name__ == "__main__":
    main()
