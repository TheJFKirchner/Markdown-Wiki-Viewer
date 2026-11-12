"""Tokens and cost: what a run used, priced at list (API) prices.

On a Claude subscription a run isn't billed per token: it counts against the plan's usage. These
figures are what the same tokens would cost at API prices, for comparing runs and models.
"""

# List prices, dollars per million tokens, by model family (Haiku 5.5, Sonnet 5.5, Opus 5.5,
# Fable 5.1). A name is matched against these in order, so an older generation that costs more is
# listed first, by its version (Haiku 4.5, the model the `haiku` alias means in older Claude Code).
# Used for the "plain Claude Code" estimate, and the run's cost if the engine doesn't report one. Cache writes are priced at the 5-minute
# rate (1.25x input). This is a set assumption, not measured.
PRICES = {
    "haiku-4": {"input": 1.00, "cache_write": 1.25, "cache_read": 0.10, "output": 5.00},
    "haiku": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
    "sonnet": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.20, "output": 10.00},
    "opus": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
    "fable": {"input": 10.00, "cache_write": 12.50, "cache_read": 0.25, "output": 50.00},
}

# Assumed extra context a plain Claude Code session sends on every request, which this run strips
# (about 35k in all, in line with what a normal session shows for its starting context).
PLAIN_CLAUDE_CODE_EXTRA = {"tools": 14_000, "system_prompt": 12_000, "claude_md_and_memory": 5_000, "skills_and_mcp": 4_000}


def prices_for(model: str) -> dict:
    """The model family's prices (Sonnet's for a family not listed)."""
    name = (model or "").lower()
    return next((PRICES[family] for family in PRICES if family in name), PRICES["sonnet"])


def tokens_of(usage) -> dict:
    """Token counts in the app's own names, from agentlib's Usage, or from a dict with the API's
    names (input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens: what
    sessions/secondbrain/llm.py passes), or None."""
    if isinstance(usage, dict) or usage is None:
        usage = usage or {}
        get = usage.get
        return {
            "input": int(get("input_tokens") or 0),
            "cacheWrite": int(get("cache_creation_input_tokens") or 0),
            "cacheRead": int(get("cache_read_input_tokens") or 0),
            "output": int(get("output_tokens") or 0),
        }
    return {
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "cacheWrite": int(getattr(usage, "cache_write_tokens", 0) or 0),
        "cacheRead": int(getattr(usage, "cache_read_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
    }


def priced(tokens: dict, prices: dict) -> float:
    return (tokens["input"] * prices["input"] + tokens["cacheWrite"] * prices["cache_write"]
            + tokens["cacheRead"] * prices["cache_read"] + tokens["output"] * prices["output"]) / 1e6


def plain_claude_code_cost(cost: float, requests: int, prices: dict) -> dict:
    """What the same run would roughly cost in a plain Claude Code session: our cost plus the
    assumed extra context on every request, written to the cache once and read back after."""
    extra = sum(PLAIN_CLAUDE_CODE_EXTRA.values())
    added = extra * prices["cache_write"] / 1e6 + extra * max(requests - 1, 0) * prices["cache_read"] / 1e6
    return {"cost": round(cost + added, 4), "extraTokensPerRequest": extra, "assumptions": PLAIN_CLAUDE_CODE_EXTRA}


def run_totals(reply, reads: int, cards: int, prices: dict) -> dict:
    """The totals for one conversation turn (the run, or one feedback round), from agentlib's Reply.
    Its cost_usd is this turn's alone (a continued conversation is opened with the cost so far).
    When the engine reports no cost (a turn that failed midway), the tokens are priced instead."""
    tokens = tokens_of(reply.usage if reply else None)
    reported = reply.cost_usd if reply else 0
    cost = reported if reported or not any(tokens.values()) else priced(tokens, prices)
    requests = reply.api_calls if reply else 0
    return {
        "cost": round(cost, 4),
        "plainClaudeCode": plain_claude_code_cost(cost, requests, prices),
        "tokens": tokens,
        "requests": requests,
        "turns": requests,
        "reads": reads,
        "cards": cards,
        "durationSeconds": round(reply.duration_s, 1) if reply and reply.duration_s else None,
        "stopReason": reply.stop_reason if reply else None,
        "errorKind": reply.error_kind if reply else None,
    }


def add_totals(before: dict | None, more: dict, prices: dict) -> dict:
    """The run's totals after a feedback round: everything adds up, and the plain-Claude-Code
    estimate is redone as if it were one session (the overhead is cached once, then read)."""
    if not before:
        return more
    total = dict(more)
    for key in ("cost", "requests", "turns", "reads"):
        total[key] = round((before.get(key) or 0) + (more.get(key) or 0), 4)
    total["durationSeconds"] = round((before.get("durationSeconds") or 0) + (more.get("durationSeconds") or 0), 1)
    total["tokens"] = {k: (before.get("tokens") or {}).get(k, 0) + more["tokens"][k] for k in more["tokens"]}
    total["plainClaudeCode"] = plain_claude_code_cost(total["cost"], total["requests"], prices)
    return total
