"""Unified Claude API client and JSON response parsing."""

import json
import requests

from job_bot.config import OPENROUTER_API_KEY, OPENROUTER_BASE, MODEL, DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE


def ask_claude(prompt, *, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE, timeout=60):
    """
    Call Claude via OpenRouter.

    Returns the response text, or "" on error. Never calls sys.exit().
    """
    if not OPENROUTER_API_KEY:
        print("  !! OPENROUTER_API_KEY not set")
        return ""

    try:
        resp = requests.post(
            OPENROUTER_BASE,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=timeout,
        )

        if resp.status_code != 200:
            print(f"  !! Claude API HTTP {resp.status_code}: {resp.text[:200]}")
            return ""

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        print(f"  !! Claude API timeout ({timeout}s)")
        return ""
    except (KeyError, IndexError) as e:
        print(f"  !! Claude API response error: {e}")
        return ""
    except Exception as e:
        print(f"  !! Claude API error: {e}")
        return ""


def parse_json_response(raw):
    """
    Parse a JSON object from a Claude response that may contain
    markdown code fences, leading text, etc.

    Returns the parsed dict/list, or None on failure.
    """
    if not raw:
        return None

    raw = raw.strip()

    # Strip markdown code fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") or cleaned.startswith("["):
                raw = cleaned
                break

    # Find the JSON object/array boundaries
    start_brace = raw.find("{")
    start_bracket = raw.find("[")

    if start_brace < 0 and start_bracket < 0:
        return None

    # Pick whichever comes first
    if start_brace >= 0 and (start_bracket < 0 or start_brace < start_bracket):
        start = start_brace
        end = raw.rfind("}") + 1
    else:
        start = start_bracket
        end = raw.rfind("]") + 1

    if end <= start:
        return None

    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None
