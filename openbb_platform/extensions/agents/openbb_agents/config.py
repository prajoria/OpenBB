"""LiteLLM model configuration for OpenBB Agents.

Model selection strategy
------------------------
Rather than hardcoding a single model, this module maintains a CANDIDATE list
ordered by preference. On first use, ``get_working_models()`` probes each
candidate against the configured API base and returns only those that respond
successfully. This means:

- New models added to CANDIDATE_MODELS are automatically picked up.
- Models that get added to your Copilot proxy licence are found without any
  code change — just restart the process (or call ``refresh_working_models()``).
- Models that stop working (quota, deprecation) fall out of the list silently.

The first working model becomes the default for analytical agents; the second
(if available) becomes the conversational model. Override via env vars at any
time.
"""

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Candidate model list — ordered by preference.
# Add new model IDs here; the probe will validate them at runtime.
# ---------------------------------------------------------------------------
CANDIDATE_MODELS: list[str] = [
    # OpenAI-format models accepted by VS Code Copilot proxy (:4141)
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/gpt-3.5-turbo",
    # Direct OpenAI (if OPENAI_API_KEY is set)
    "gpt-4o",
    "gpt-4o-mini",
    # Anthropic (if ANTHROPIC_API_KEY is set)
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-3-5-sonnet-20241022",
    # Gemini (if GEMINI_API_KEY is set)
    "gemini/gemini-1.5-pro",
    "gemini/gemini-1.5-flash",
    # Local Ollama fallback
    "ollama/llama3.1",
    "ollama/mistral",
]

# ---------------------------------------------------------------------------
# Connection config — override via env vars
# ---------------------------------------------------------------------------
LITELLM_BASE_URL: str = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4141")
LITELLM_API_KEY: str = os.getenv("LITELLM_API_KEY", "copilot")

PROBE_TIMEOUT: float = float(os.getenv("OPENBB_AGENTS_PROBE_TIMEOUT", "6"))
PROBE_MESSAGE = [{"role": "user", "content": "reply with the single word: pong"}]

# ---------------------------------------------------------------------------
# Env-var overrides (bypass probe entirely when set)
# ---------------------------------------------------------------------------
_MODEL_OVERRIDE: Optional[str] = os.getenv("OPENBB_AGENTS_MODEL")
_CONV_OVERRIDE: Optional[str] = os.getenv("OPENBB_AGENTS_CONV_MODEL")


def probe_model(model: str) -> bool:
    """Return True if ``model`` responds successfully via the configured base URL."""
    try:
        import litellm  # lazy import — don't force at module load time

        litellm.suppress_debug_info = True
        r = litellm.completion(
            model=model,
            api_base=LITELLM_BASE_URL,
            api_key=LITELLM_API_KEY,
            messages=PROBE_MESSAGE,
            timeout=PROBE_TIMEOUT,
        )
        _ = r.choices[0].message.content  # ensure content is accessible
        logger.debug("Model probe OK: %s", model)
        return True
    except Exception as exc:
        logger.debug("Model probe FAIL: %s — %s", model, str(exc)[:120])
        return False


@lru_cache(maxsize=1)
def get_working_models() -> list[str]:
    """Probe all candidates and return those that respond successfully.

    Result is cached for the lifetime of the process. Call
    ``refresh_working_models()`` to force a re-probe (e.g. after a Copilot
    proxy restart).
    """
    logger.info("Probing %d candidate models against %s …", len(CANDIDATE_MODELS), LITELLM_BASE_URL)
    working = [m for m in CANDIDATE_MODELS if probe_model(m)]
    if working:
        logger.info("Working models: %s", working)
    else:
        logger.warning("No working models found — all probes failed. Check LITELLM_BASE_URL.")
    return working


def refresh_working_models() -> list[str]:
    """Clear the probe cache and re-probe all candidates."""
    get_working_models.cache_clear()
    return get_working_models()


def get_analytical_model() -> str:
    """Return the best available model for analytical (temperature=0) tasks."""
    if _MODEL_OVERRIDE:
        return _MODEL_OVERRIDE
    working = get_working_models()
    if not working:
        raise RuntimeError(
            "No working LLM models found. "
            "Ensure VS Code Copilot proxy is running at "
            f"{LITELLM_BASE_URL} or set OPENBB_AGENTS_MODEL env var."
        )
    return working[0]


def get_conversational_model() -> str:
    """Return the best available model for conversational (temperature=0.2) tasks."""
    if _CONV_OVERRIDE:
        return _CONV_OVERRIDE
    working = get_working_models()
    if not working:
        raise RuntimeError("No working LLM models found.")
    # Prefer second model for conversational (keeps analytical and conversational separate)
    return working[1] if len(working) > 1 else working[0]


def get_litellm_config(conversational: bool = False) -> dict:
    """Return kwargs dict suitable for litellm.completion or ADK LiteLlm init."""
    model = get_conversational_model() if conversational else get_analytical_model()
    return {
        "model": model,
        "api_base": LITELLM_BASE_URL,
        "api_key": LITELLM_API_KEY,
        "temperature": 0.2 if conversational else 0.0,
    }


# Convenience constants (resolved lazily — don't probe at import time)
ANALYTICAL_TEMPERATURE: float = 0.0
CONVERSATIONAL_TEMPERATURE: float = 0.2
