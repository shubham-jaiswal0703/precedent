"""Every model call in one place, with a live tier probe and a result cache.

Two problems this exists to solve.

**The tier can die under you.** VideoDB's text calls default to `model_name
"basic"`, hackathon budgets are per tier, and there is no usage endpoint to
check what is left. A spent tier fails on every call, which for us would look
like the contradiction finder and the grounded answers quietly having nothing to
say. So the model is resolved once by actually calling each tier in order and
keeping the first that answers.

**We were paying twice for the same answer.** Judging a witness pair is the
slowest thing in the product, and re-running it with an unchanged prompt used to
re-pay for every verdict. Output is cached against a hash of the prompt, so
iterating on prompt wording costs only the calls whose wording changed.
"""
import hashlib
import json
import os
import threading
from typing import Any, Optional

from . import store
from .config import get_connection

TIER_CHAIN = ("basic", "pro", "ultra")
MODEL_DOC = "llm_model"
CACHE_DOC = "llm_cache"

_LOCK = threading.Lock()
_RESOLVED: Optional[str] = None
_CACHE: Optional[dict] = None


class LlmUnavailable(RuntimeError):
    """No model tier answered. Raised rather than returning empty output."""


def _probe(model_name: str) -> bool:
    """One cheap live call. A budget failure only shows up by trying."""
    try:
        coll = get_connection().get_collection()
        coll.generate_text(prompt="Reply with the single word: ok",
                           model_name=model_name, response_type="text")
        return True
    except Exception as exc:
        print(f"[llm] tier '{model_name}' unavailable: {str(exc)[:160]}")
        return False


def resolve_model(refresh: bool = False) -> str:
    """The first tier that answers, remembered across restarts."""
    global _RESOLVED
    with _LOCK:
        if _RESOLVED and not refresh:
            return _RESOLVED
        remembered = (store.read(MODEL_DOC) or {}).get("model")
        if remembered and not refresh:
            _RESOLVED = remembered
            return _RESOLVED

    override = os.environ.get("PRECEDENT_LLM_MODEL", "").strip()
    chain = (override,) + TIER_CHAIN if override else TIER_CHAIN
    for model_name in chain:
        if _probe(model_name):
            with _LOCK:
                _RESOLVED = model_name
            store.write(MODEL_DOC, {"model": model_name})
            print(f"[llm] using model tier '{model_name}'")
            return model_name
    raise LlmUnavailable(
        "No VideoDB model tier answered (tried: " + ", ".join(chain) + "). "
        "The tier budget is likely spent; there is no usage endpoint to confirm."
    )


def _cache() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = store.read(CACHE_DOC, {}) or {}
        return _CACHE


def _cache_key(prompt: str, response_type: str, tag: str) -> str:
    digest = hashlib.sha256(f"{tag}|{response_type}|{prompt}".encode()).hexdigest()
    return digest[:40]


def _remember(key: str, value: str) -> None:
    cache = _cache()
    with _LOCK:
        cache[key] = value
        if len(cache) > 4000:  # bounded; oldest keys are the least useful
            for stale in list(cache)[:1000]:
                cache.pop(stale, None)
    store.write(CACHE_DOC, cache)


def generate(prompt: str, response_type: str = "text", tag: str = "",
             use_cache: bool = True) -> str:
    """Model output as text. Cached against the exact prompt.

    `tag` namespaces the cache so two features asking the same question keep
    separate entries, and so changing a prompt template invalidates only its own
    entries.
    """
    key = _cache_key(prompt, response_type, tag)
    if use_cache:
        hit = _cache().get(key)
        if hit is not None:
            return hit

    model_name = resolve_model()
    coll = get_connection().get_collection()
    try:
        result = coll.generate_text(prompt=prompt, model_name=model_name,
                                    response_type=response_type)
    except Exception as exc:
        # A tier can die mid-session, so re-probe once before giving up.
        print(f"[llm] '{model_name}' failed mid-session ({str(exc)[:120]}); re-probing")
        model_name = resolve_model(refresh=True)
        result = coll.generate_text(prompt=prompt, model_name=model_name,
                                    response_type=response_type)

    if isinstance(result, dict):
        text = str(result.get("output", result))
    else:
        text = str(getattr(result, "output", result))
    if use_cache:
        _remember(key, text)
    return text


def vision_model() -> Optional[str]:
    """Tier to pass to scene indexing and describe calls.

    Vision and text budgets are tracked separately, so the resolved text tier is
    only a hint. Returning None lets the SDK pick its default, which is the
    safer behaviour when we have no evidence about the vision tier.
    """
    return os.environ.get("PRECEDENT_VISION_MODEL", "").strip() or None


def cache_stats() -> dict:
    return {"model": _RESOLVED or (store.read(MODEL_DOC) or {}).get("model"),
            "cached_answers": len(_cache())}
