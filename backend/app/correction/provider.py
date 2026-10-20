"""AI-provider seam for the correction engine.

The engine depends on the small :class:`ModelClient` protocol, so the real
Gemini client and the deterministic test client are interchangeable. The
Gemini implementation uses the REST API through the standard library — no SDK
and no extra dependency — and keeps the key server-side.

Failure rules:

* every failure becomes a :class:`ProviderFailure` whose message is safe to
  show a user;
* retries are bounded and only happen for transient failures (timeouts,
  429 and 5xx);
* response bodies, prompts, student content and the API key are never logged;
* nothing here fabricates a result.
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from ..engine import ProviderError

log = logging.getLogger("mathchecker.correction.provider")

# Gemini accepts larger requests through its Files API. This build sends
# documents inline, so the engine keeps the whole request under this bound and
# tells the user when a document had to be left out of the visual payload.
# 12 MiB of raw bytes becomes about 16 MiB once base64-encoded, leaving room
# for the prompt inside the provider's ~20 MB inline request limit.
MAX_INLINE_BYTES = 12 * 1024 * 1024


class ProviderFailure(ProviderError):
    """A provider call failed. ``retryable`` marks transient conditions."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class ModelAttachment:
    """One document sent to the model for visual interpretation."""

    filename: str
    media_type: str
    data: bytes


@dataclass(frozen=True)
class ModelRequest:
    system_prompt: str
    user_prompt: str
    attachments: tuple[ModelAttachment, ...] = ()


class ModelClient(Protocol):
    """What the engine needs from an AI provider."""

    name: str

    def generate(self, request: ModelRequest) -> str: ...


class GeminiClient:
    """Minimal Gemini ``generateContent`` client (stdlib HTTP only)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: int = 120,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise ValueError("A provider API key is required.")
        self._api_key = api_key
        self._model = model.removeprefix("models/")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self.name = f"gemini:{self._model}"

    def generate(self, request: ModelRequest) -> str:
        payload = self._build_payload(request)
        last_error: ProviderFailure | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._post(payload)
            except ProviderFailure as exc:
                last_error = exc
                if not exc.retryable or attempt >= self._max_retries:
                    break
                delay = min(8.0, 1.0 * (2**attempt))
                log.warning(
                    "provider call failed (%s); retrying in %.0fs (attempt %d/%d)",
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                self._sleep(delay)
        assert last_error is not None
        raise last_error

    # --- internals -------------------------------------------------------

    def _build_payload(self, request: ModelRequest) -> dict:
        parts: list[dict] = []
        for attachment in request.attachments:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": attachment.media_type,
                        "data": base64.b64encode(attachment.data).decode("ascii"),
                    }
                }
            )
        parts.append({"text": request.user_prompt})
        return {
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "topP": 0.9,
                "maxOutputTokens": 16384,
                "responseMimeType": "application/json",
            },
        }

    def _endpoint(self) -> str:
        model = urllib.parse.quote(self._model, safe="")
        return f"{self._base_url}/v1beta/models/{model}:generateContent"

    def _post(self, payload: dict) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint(),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            # Never read or include the response body: it can echo prompt text
            # or provider diagnostics. The status code is enough to act on.
            status = exc.code
            log.warning("provider HTTP %s for model %s", status, self._model)
            raise ProviderFailure(_message_for_status(status), retryable=status in (429, 500, 502, 503, 504)) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            log.warning("provider transport failure: %s", type(exc).__name__)
            raise ProviderFailure(
                "The AI provider could not be reached. Check the server's network connection and try again.",
                retryable=True,
            ) from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("provider returned non-JSON response")
            raise ProviderFailure("The AI provider returned an unreadable response.") from exc

        return _extract_text(data, self._model)


def _message_for_status(status: int) -> str:
    if status in (401, 403):
        return "The AI provider rejected the configured API key."
    if status == 404:
        return "The configured AI model is not available to this provider key."
    if status == 429:
        return "The AI provider is rate-limiting requests. Try again shortly."
    if 500 <= status <= 599:
        return "The AI provider is temporarily unavailable. Try again shortly."
    return "The AI provider could not process the request."


def _extract_text(data: dict, model: str) -> str:
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        log.warning("provider blocked the request (%s)", feedback.get("blockReason"))
        raise ProviderFailure(
            "The AI provider declined to process this submission. Check that the files are appropriate."
        )

    candidates = data.get("candidates") or []
    if not candidates:
        raise ProviderFailure("The AI provider returned no result.")

    candidate = candidates[0]
    finish_reason = str(candidate.get("finishReason") or "")
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    text = "".join(
        str(part.get("text", "")) for part in parts if isinstance(part, dict)
    ).strip()

    if not text:
        if finish_reason == "MAX_TOKENS":
            raise ProviderFailure(
                "The AI provider's response was cut off before it finished."
            )
        if finish_reason in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise ProviderFailure(
                "The AI provider declined to process this submission."
            )
        raise ProviderFailure("The AI provider returned an empty response.")

    if finish_reason == "MAX_TOKENS":
        # A truncated JSON body cannot be trusted even if it is non-empty.
        raise ProviderFailure(
            "The AI provider's response was cut off before it finished."
        )
    return text


def describe_provider(config) -> str:
    """Human-readable provider name without any secret material."""
    return f"gemini:{config.model.removeprefix('models/')}"
