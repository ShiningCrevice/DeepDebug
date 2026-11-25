"""Bounded Responses API transport for explicitly authorized reviewed sessions."""

import asyncio
import json
import os
from time import monotonic

import httpx

from deepdebug.llm.client import ModelFailure, ModelRequest, ModelResponse
from deepdebug.security.outbound import OutboundBoundary
from deepdebug.security.redaction import Redactor

MAX_RESPONSE_BYTES = 1024 * 1024


class OpenAIResponsesClient:
    transport = "remote"

    def __init__(self, boundary: OutboundBoundary):
        self.boundary = boundary
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in self._api_key):
            raise ValueError("请通过 OPENAI_API_KEY 环境变量提供有效密钥。")

    async def _send(self, payload: dict, timeout: float) -> dict:
        # Use the confirmed destination without redirects, environment proxies or SDK retries.
        async with httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=timeout
        ) as client:
            async with client.stream(
                "POST",
                self.boundary.consent.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as response:
                if response.status_code != 200:
                    transient = response.status_code in {408, 429} or response.status_code >= 500
                    raise ModelFailure(
                        "unavailable" if transient else "error",
                        usage_unknown=transient,
                        http_status=response.status_code,
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ModelFailure("error", usage_unknown=True)
                return json.loads(body)

    async def _timed_send(self, payload: dict, timeout: float) -> dict:
        # Includes connection, all response chunks and closing the HTTP client.
        return await asyncio.wait_for(self._send(payload, timeout), timeout=timeout)

    def decide(self, request: ModelRequest) -> ModelResponse:
        started = monotonic()
        try:
            request = ModelRequest.model_validate(request)
            payload = self.boundary.payload(request, api_key=self._api_key)
        except ValueError:
            raise ModelFailure("error") from None
        # UTF-8 bytes plus framing reserve are a conservative input allowance, not usage.
        input_allowance = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024
        output_allowance = min(4096, request.max_tokens - input_allowance)
        if output_allowance < 16:
            raise ModelFailure("budget")
        payload["max_output_tokens"] = output_allowance
        remaining = request.timeout_seconds - (monotonic() - started)
        if remaining <= 0:
            raise ModelFailure("budget")
        try:
            raw = asyncio.run(self._timed_send(payload, remaining))
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise ModelFailure("timeout", usage_unknown=True) from None
        except httpx.TransportError:
            raise ModelFailure("unavailable", usage_unknown=True) from None
        except (ValueError, RecursionError):
            raise ModelFailure("error", usage_unknown=True) from None
        return self._parse(raw)

    def _parse(self, raw: dict) -> ModelResponse:
        try:
            usage = raw["usage"]
            result = ModelResponse(
                content="",
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
            )
        except (KeyError, TypeError, ValueError):
            raise ModelFailure("error", usage_unknown=True) from None
        # Retain known usage even when generation is refused, incomplete or malformed.
        if raw.get("status") != "completed":
            result.failure = "incomplete" if raw.get("status") == "incomplete" else "error"
            return result
        try:
            parts = []
            for item in raw["output"]:
                if item["type"] == "reasoning":
                    continue
                if item["type"] != "message" or item.get("role") != "assistant":
                    result.failure = "error"
                    return result
                for part in item["content"]:
                    if part["type"] == "refusal":
                        result.failure = "refused"
                        return result
                    if part["type"] != "output_text" or not isinstance(part["text"], str):
                        result.failure = "error"
                        return result
                    parts.append(part["text"])
            content = "".join(parts)
            if not content:
                result.failure = "error"
            else:
                result.content = Redactor([content], secrets=[self._api_key]).redact(content)
        except (KeyError, TypeError, ValueError, RecursionError):
            result.failure = "error"
        return ModelResponse.model_validate(result)
