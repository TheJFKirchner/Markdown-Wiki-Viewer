"""One-shot model calls, through agentlib (the engine-neutral agent library WikiApp runs on).

Each call is one structured request: the model replies in a fixed JSON shape (a JSON Schema),
which agentlib checks before the reply is used. The call has no tools and saves no conversation,
so it cannot touch files and never shows up in the list of sessions to capture. The engine
(Claude today) comes from the app's engine settings (engine.json, host/pathlist.py), or the
config's `engine` ("fake" in tests: agentlib's fake engine, which spends nothing).
"""
from __future__ import annotations

import sys

from .config import ROOT, pathlist
from .transcripts import SENTINEL

sys.path.insert(0, str(ROOT.parent / "ingest"))
import costs  # noqa: E402  (the app's price table, shared with the Notes and Promotion runs)

SYSTEM = (
    "You are a text-processing function inside a note-taking pipeline. "
    "Reply only in the JSON shape you are given."
)
ANY_OBJECT = {"type": "object"}


class LLMError(Exception):
    pass


# What the calls made so far in this command cost: each request's tokens, priced from the app's
# own table of API list prices (ingest/costs.py) for the model that answered. The engine's own
# figure isn't used: an older Claude Code prices a model it doesn't know at a fallback rate (it
# reported Haiku 5.5 at fifty times the table's price). On a subscription nothing is billed per
# token; the figure still shows how heavy a request was. take_spend() returns the total and starts again.
_spend = {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "calls": 0, "model": ""}


def take_spend() -> dict:
    out = {**_spend, "cost": round(_spend["cost"], 6)}
    _spend.update(cost=0.0, tokens_in=0, tokens_out=0, calls=0, model="")
    return out


def _note_spend(reply, asked_for: str = "") -> None:
    """Adds one reply's tokens (agentlib's Reply.usage) to the running total."""
    usage = getattr(reply, "usage", None)
    if usage is None:
        return
    model = getattr(reply, "model", "") or asked_for  # the model that answered, by its exact id
    tokens = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": usage.cache_read_tokens,
        "cache_creation_input_tokens": usage.cache_write_tokens,
    }
    _spend["model"] = model
    _spend["cost"] += costs.priced(costs.tokens_of(tokens), costs.prices_for(model))
    _spend["tokens_in"] += int(usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens)
    _spend["tokens_out"] += int(usage.output_tokens)
    _spend["calls"] += 1


def engine_name(cfg) -> str:
    """The engine the requests run on: the config's, else the app's engine settings."""
    if getattr(cfg, "engine", ""):
        return cfg.engine
    try:
        return pathlist.get_engine_settings()["engine"]
    except Exception:
        return "claude"


def call_json(cfg, prompt: str, model: str, thinking: bool = True, schema: dict | None = None,
              name: str = "secondbrain") -> dict:
    """Send the prompt and return the JSON object it replies with, already checked against the
    schema. Retries once when the reply has the wrong shape. name: the agent's name (the fake
    engine's scripts are looked up by it)."""
    try:
        from agentlib import AgentError, ask_structured_sync
    except ImportError as e:
        raise LLMError("The AI features are off: the agentlib library isn't installed in this Python. "
                       "Start WikiApp once to install it (or run pip install -e on the agentlib folder).") from e
    from . import wiki
    engine = engine_name(cfg)
    workdir = wiki.state_dir(cfg.personal) / "llm"
    workdir.mkdir(parents=True, exist_ok=True)
    env = {}
    if engine == "claude":
        # Each call is one request that is never repeated, so writing it to the prompt cache only
        # adds the cache-write surcharge. And without extended thinking the model writes just its
        # answer: on a capture, thinking was most of the output tokens, which cost five times the input ones.
        env["DISABLE_PROMPT_CACHING"] = "1"
        if not thinking:
            env["MAX_THINKING_TOKENS"] = "0"
    last: LLMError | None = None
    for _ in range(2):
        try:
            reply = ask_structured_sync(
                SENTINEL + "\n" + prompt, schema or ANY_OBJECT,
                instructions=SYSTEM, model=model or None, engine=engine, name=name,
                timeout_s=cfg.llm_timeout_seconds, env=env or None, cwd=str(workdir),
            )
        except AgentError as e:  # the engine itself failed: not signed in, timed out, process died
            if getattr(e, "reply", None) is not None:
                _note_spend(e.reply, model)
            raise LLMError(f"Model call failed: {getattr(e, 'short', '') or e}") from e
        except Exception as e:  # an unknown engine, or one that can't do structured replies
            raise LLMError(f"Model call failed: {type(e).__name__}: {e}") from e
        _note_spend(reply, model)  # a request that came back is paid for, whatever was in it
        if reply.status != "error" and isinstance(reply.data, dict):
            return reply.data
        if reply.status != "error":
            last = LLMError("The model's reply was not a JSON object.")
        elif reply.error_kind == "output_shape":
            last = LLMError(f"The model's reply had the wrong shape: {reply.error}")
        else:
            raise LLMError(f"Model call failed ({reply.error_kind}): {reply.error}")
    raise last  # type: ignore[misc]
