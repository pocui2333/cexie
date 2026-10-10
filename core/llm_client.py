"""
OpenAI 兼容协议的统一调用客户端。
所有大模型请求（生成 / 解析 / 视觉描述 / 情感过滤 / 知识提炼）统一走这里，
保证 TLS 校验、超时与 JSON 容错行为一致。
"""
import json
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional

import config

_SSL_CTX: Optional[ssl.SSLContext] = None


def ssl_context() -> ssl.SSLContext:
    """始终校验证书：优先使用 certifi 证书包，缺失时退回系统默认证书（绝不降级为不校验）"""
    global _SSL_CTX
    if _SSL_CTX is None:
        try:
            import certifi
            _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def is_enabled() -> bool:
    return bool(config.LLM_API_KEY)


def chat_completion(
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout: float = 12.0,
    model: Optional[str] = None,
) -> str:
    """发起一次 chat/completions 请求并返回首条回复文本；网络或协议异常直接抛出"""
    body: Dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(
        f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ssl_context(), timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def extract_json(content: str, want: str = "object") -> Any:
    """从模型输出中容错提取 JSON（去除 ``` 包裹与尾逗号）；want 为 'object' 或 'array'，失败返回 None"""
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content)
    pattern = r"\{.*\}" if want == "object" else r"\[.*\]"
    m = re.search(pattern, content, re.DOTALL)
    if not m:
        return None
    raw = m.group(0)
    for candidate in (re.sub(r",\s*([\]}])", r"\1", raw), raw):
        try:
            return json.loads(candidate, strict=False)
        except ValueError:
            continue
    return None
