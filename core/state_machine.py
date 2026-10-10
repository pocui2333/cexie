from datetime import datetime


class SessionStateMachine:
    """
    当前会话的轻量内存态:
    - 当前目标联系人 (active_target)
    - 最近一条对方消息的发送人与时间 (供 HUD 展示)
    长期记忆沉淀统一由 EpisodicDistiller.record_turns 在每次抓取时增量完成，
    这里不再缓存会话消息、也不做超时整批归档 (旧实现会把已沉淀的消息重复写入)。
    """
    def __init__(self, default_target: str = "示例好友"):
        self.active_target: str = default_target
        self.last_sender_name: str = default_target
        self.last_incoming_time_str: str = "刚刚"
        self.current_incoming_text: str = ""

    def feed_incoming_message(self, target_name: str, content: str) -> None:
        self.active_target = target_name
        self.last_sender_name = target_name
        self.current_incoming_text = content
        self.last_incoming_time_str = datetime.now().strftime("%H:%M:%S")
