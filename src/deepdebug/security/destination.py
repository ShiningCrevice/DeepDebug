"""Resolve an OpenAI-style API prefix to the destination the user confirms."""

from pydantic import AnyHttpUrl

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _http_url(value: str) -> str:
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("API 地址不能包含空白或控制字符。")
    url = AnyHttpUrl(value)
    if (
        url.username is not None
        or url.password is not None
        or url.query is not None
        or url.fragment is not None
    ):
        raise ValueError("API 地址不能包含凭据、查询参数或片段。")
    return str(url).rstrip("/")


def responses_endpoint(base_url: str) -> str:
    base_url = _http_url(base_url)
    if base_url.endswith("/responses"):
        raise ValueError("base_url 应为 API 基础地址，不含 /responses。")
    return base_url + "/responses"


def normalize_endpoint(endpoint: str) -> str:
    endpoint = _http_url(endpoint)
    if not endpoint.endswith("/responses"):
        raise ValueError("发送目的地必须以 /responses 结尾。")
    return endpoint
