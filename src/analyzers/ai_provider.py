from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

import requests

from src.config.settings import Settings
from src.utils.cache import DiskCache
from src.utils.logging import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


def _extract_json(text: str) -> dict[str, Any]:
    """AI 응답에서 JSON 블록 추출 (마크다운 펜스 포함)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"AI 응답이 JSON 아님: {text[:200]}")


class AIProvider(ABC):
    """AI Provider 인터페이스. OpenAI/Anthropic/Google/Mock 을 스위칭."""

    name: str = "base"

    def __init__(self, cache: DiskCache | None = None) -> None:
        self.cache = cache

    @abstractmethod
    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        """구조화된 JSON 응답을 반환."""
        raise NotImplementedError

    def _cached(self, key: str, producer) -> dict[str, Any]:
        if not self.cache:
            return producer()
        cached = self.cache.get(key)
        if cached is not None:
            return cached["data"]
        value = producer()
        self.cache.set(key, {"data": value})
        return value


class OpenAIProvider(AIProvider):
    """OpenAI Chat Completions. API 응답은 JSON 형식 유도."""

    name = "openai"

    def __init__(self, api_key: str, model: str, *, max_tokens: int = 3000, timeout: int = 120, base_url: str | None = None, cache=None) -> None:
        super().__init__(cache)
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.base_url = base_url or "https://api.openai.com/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    @retry(max_attempts=3, base_delay=2, max_delay=30, logger=logger)
    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        resp = self.session.post(f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _extract_json(content)


class AnthropicProvider(AIProvider):
    """Anthropic Messages API. JSON prefill 로 구조화 응답 유도."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, *, max_tokens: int = 3000, timeout: int = 120, cache=None) -> None:
        super().__init__(cache)
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        })

    @retry(max_attempts=3, base_delay=2, max_delay=30, logger=logger)
    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }
        resp = self.session.post("https://api.anthropic.com/v1/messages", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        content = "".join(b.get("text", "") for b in resp.json()["content"])
        return _extract_json(content)


class MockProvider(AIProvider):
    """테스트/키 없는 환경용 Mock. AI 호출 비용 0."""

    name = "mock"

    def __init__(self, canned: dict[str, Any] | None = None, cache=None) -> None:
        super().__init__(cache)
        self.canned = canned or {}

    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        if self.canned:
            return dict(self.canned)
        return {
            "facts": [
                {
                    "claim": "확인된 사실: 가격·거래량 데이터에 따르면 해당 종목의 거래량이 평균 대비 크게 증가했다.",
                    "type": "fact",
                    "confidence": 0.95,
                    "source_ids": ["stock"],
                }
            ],
            "hypotheses": [
                {
                    "claim": "뉴스·공시 자료에서 직접 확인된 단일 원인은 확인되지 않았다.",
                    "type": "hypothesis",
                    "confidence": 0.6,
                    "source_ids": [],
                }
            ],
            "key_drivers": ["거래량 급증", "주가 변동"],
            "unknowns": ["명확한 상승/하락의 단일 원인"],
            "summary": "집계된 데이터상 거래량 급증이 관찰되며, 원인은 추가 자료로 확인해야 한다.",
        }


class ProviderFactory:
    """설정에 따라 AI Provider 반환."""

    def __init__(self, settings: Settings, cache: DiskCache | None = None) -> None:
        self.settings = settings
        self.cache = cache

    def build(self) -> AIProvider:
        env = os.environ
        provider = self.settings.ai.provider
        if provider == "auto":
            if env.get("OPENAI_API_KEY"):
                provider = "openai"
            elif env.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif env.get("GOOGLE_API_KEY"):
                provider = "google"
            else:
                provider = "mock"
        if provider == "mock":
            return MockProvider(cache=self.cache)
        if provider == "openai":
            key = env.get("OPENAI_API_KEY", "")
            model = env.get("OPENAI_MODEL", self.settings.ai.model)
            if self.settings.ai.model != "auto" and not env.get("OPENAI_MODEL"):
                model = self.settings.ai.model
            if not key:
                logger.warning("OPENAI_API_KEY 없음 -> mock provider 사용")
                return MockProvider(cache=self.cache)
            return OpenAIProvider(
                key,
                model if model != "auto" else "gpt-4o-mini",
                max_tokens=self.settings.ai.max_tokens,
                timeout=self.settings.ai.timeout_seconds,
                cache=self.cache,
            )
        if provider == "anthropic":
            key = env.get("ANTHROPIC_API_KEY", "")
            model = env.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
            if not key:
                logger.warning("ANTHROPIC_API_KEY 없음 -> mock provider 사용")
                return MockProvider(cache=self.cache)
            return AnthropicProvider(
                key,
                model,
                max_tokens=self.settings.ai.max_tokens,
                timeout=self.settings.ai.timeout_seconds,
                cache=self.cache,
            )
        raise ValueError(f"unsupported ai provider: {provider}")