"""Google Gemini (Generative Language REST API) client used by the help chat and insights summary.

Plain HTTPS through ``requests``: no extra SDK. Only used when the Owner has switched on the
'gemini' integration.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-latest"
# Tried in order after the Owner's chosen model when Google says it is overloaded or retired.
FALLBACK_MODELS = ("gemini-flash-latest", "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-2.5-flash")
RETRY_STATUS = {500, 502, 503, 504}
GONE_STATUS = {404}


class GeminiError(Exception):
    pass


def _post(model, api_key, body, timeout):
    resp = requests.post(
        API.format(model=model),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    return resp.status_code, data, resp.text


def generate(config, contents, system="", tools=None, max_tokens=2048, timeout=25, budget=30):
    """Call generateContent and return the first candidate's content dict ({"role": "model", "parts": [...]}).

    Google often answers 503 "high demand". Each model gets a short retry, then the next model in
    FALLBACK_MODELS is tried, all within ``budget`` seconds so a customer is never left waiting long.
    """
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    first = (config.get("model") or DEFAULT_MODEL).removeprefix("models/")
    models = [first] + [m for m in FALLBACK_MODELS if m != first]
    deadline = time.monotonic() + budget
    errors = []
    for model in models:
        for attempt in range(2):
            left = deadline - time.monotonic()
            if left <= 1:
                raise GeminiError("Gemini did not answer in time. Tried: " + "; ".join(errors))
            try:
                status, data, raw = _post(model, config["api_key"], body, min(timeout, left))
            except requests.RequestException as exc:
                errors.append(f"{model}: {exc.__class__.__name__}")
                continue
            if status == 200:
                candidates = data.get("candidates") or []
                if not candidates:
                    reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
                    raise GeminiError(f"Gemini returned no answer ({reason}).")
                if errors:
                    logger.warning("Gemini answered with %s after: %s", model, "; ".join(errors))
                return candidates[0].get("content") or {"role": "model", "parts": []}
            message = (data.get("error") or {}).get("message") or raw[:200]
            errors.append(f"{model}: HTTP {status} {message[:90]}")
            if status == 429:
                break  # quota used up for this model: waiting a second won't help, try the next model
            if status in RETRY_STATUS:
                if attempt == 0:
                    time.sleep(min(1.5, max(0, deadline - time.monotonic() - 1)))
                continue
            if status in GONE_STATUS:
                break  # this model is retired or unknown: try the next one
            raise GeminiError(f"HTTP {status}: {message}")  # bad key, bad request: no point retrying
    raise GeminiError("All Gemini models failed. " + "; ".join(errors))


def text_of(content):
    return "".join(p.get("text", "") for p in content.get("parts", []) if not p.get("thought")).strip()


def function_calls(content):
    return [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]


def declarations(anthropic_tools):
    """Convert our Anthropic-style tool list to Gemini function declarations."""
    return [
        {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]} for t in anthropic_tools
    ]


def test_connection(config):
    content = generate(config, [{"role": "user", "parts": [{"text": "Say OK"}]}], timeout=20, budget=40)
    return True, f"Gemini replied: {text_of(content)[:40] or 'OK'} (model {config.get('model') or DEFAULT_MODEL})."
