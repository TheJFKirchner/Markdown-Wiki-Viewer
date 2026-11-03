"""Prints the Claude models this computer's Claude Code offers, for the Ingest view's model menu:
a JSON list of {"id": "claude-haiku-5-5", "name": "Haiku 5.5", "description": "Fastest for quick answers"}.

The list comes from Claude Code's start-up handshake (the Claude Agent SDK's server info), so
it follows the user's sign-in and Claude Code version. Nothing is sent to Claude: no request is
made, so it costs nothing. Takes a few seconds, because Claude Code starts and stops.

   python models.py
"""

import asyncio
import json
import sys


async def models() -> list[dict]:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options = ClaudeAgentOptions(tools=[], setting_sources=[], permission_mode="dontAsk",
                                 env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    async with ClaudeSDKClient(options) as client:
        info = await client.get_server_info() or {}
    found = {}
    for model in info.get("models") or []:
        model_id = model.get("resolvedModel") or model.get("value")
        if not model_id or not model_id.startswith("claude-") or model_id in found:
            continue  # aliases ("default", "opus") name a model listed again under its own name
        # "Haiku 5.5 · Fastest for quick answers" -> the name and what it's for.
        name, _, description = (model.get("description") or "").partition(" · ")
        found[model_id] = {"id": model_id, "name": name.strip() or model.get("displayName") or model_id,
                           "description": description.strip()}
    return list(found.values())


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        print(json.dumps(asyncio.run(models()), ensure_ascii=False))
        return 0
    except Exception as err:  # the app shows this and keeps its last list
        print(f"{type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
