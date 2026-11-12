"""Prints the models the engine offers, for the model menus: a JSON list of
{"id": "claude-haiku-5-5", "name": "Haiku 5.5", "description": "Fastest for quick answers"}.

The list comes from agentlib (list_models), for the engine the engine settings name (Claude
today). On Claude it is read from Claude Code's start-up handshake, so it follows the user's
sign-in and Claude Code version. Nothing is sent to the model: no request is made, so it costs
nothing. Takes a few seconds, because Claude Code starts and stops.

   python models.py
"""

import json
import sys

from agentlib import AgentError, list_models_sync

# Model ids worth offering, per engine. Claude's list can carry entries that aren't a model of
# their own (an alias such as "default" when it doesn't resolve to a full id); the menu wants ids
# Agent(model=...) takes as they are.
ID_PREFIX = {"claude": "claude-"}


def models(engine: str | None = None) -> list[dict]:
    """The engine's models, one per id, in the engine's order. Raises AgentError when the engine
    can't be asked (not installed, not signed in)."""
    from agent import engine_choice, engine_env  # the engine and its settings come from the path list
    chosen, fields = engine_choice()
    engine = engine or chosen
    prefix = ID_PREFIX.get(engine, "")
    found = {}
    for model in list_models_sync(engine, env=engine_env(engine, fields)):
        if not model.id or not model.id.startswith(prefix) or model.id in found:
            continue
        found[model.id] = {"id": model.id, "name": model.name or model.id, "description": model.description or ""}
    return list(found.values())


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        print(json.dumps(models(), ensure_ascii=False))
        return 0
    except AgentError as err:  # the app shows this and keeps its last list
        print(getattr(err, "short", "") or str(err), file=sys.stderr)
        return 1
    except Exception as err:
        print(f"{type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
