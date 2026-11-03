"""The run's record, transcript.json: each request to Claude with its tokens, cost and the tools
it called, the cards, the totals, and any feedback rounds. The app's Past runs list shows it.
Written when the run ends (also when it fails), and extended by each feedback round.
"""

import json
from datetime import datetime
from pathlib import Path

from costs import priced, tokens_of


class Transcript:
    def __init__(self, job: dict, run_folder: Path, prices: dict):
        self.run_folder = run_folder
        self.prices = prices
        self.data = {
            "runId": job.get("runId"),
            "started": datetime.now().isoformat(timespec="seconds"),
            "finished": None,
            "model": None,
            "ok": False,
            "message": "",
            "notes": list(job.get("notes") or []),
            "context": {},  # approximate tokens of what was sent up front
            "steps": [],    # one per request to Claude
            "cards": [],
            "totals": None,
        }
        self.by_message = {}
        self.tool_calls = {}
        self.streaming = None  # id of the request whose answer is streaming in
        self.round = 0         # 0: the run itself; 1, 2...: feedback rounds

    @classmethod
    def load(cls, job: dict, run_folder: Path, prices: dict) -> "Transcript":
        """The transcript of a finished run, to add a feedback round to."""
        transcript = cls(job, run_folder, prices)
        transcript.data = json.loads((run_folder / "transcript.json").read_text(encoding="utf-8"))
        transcript.data.setdefault("feedback", [])
        return transcript

    def context(self, instructions: str, indexes: dict[str, str], notes: dict[str, str]) -> None:
        approx = lambda text: len(text) // 4
        self.data["context"] = {
            "systemPrompt": approx(instructions),
            "indexes": {alias: approx(text) for alias, text in indexes.items()},
            "notes": {note_id: approx(text) for note_id, text in notes.items()},
        }

    # ---- What comes back from Claude, request by request ------------------------------------

    def step_for(self, message_id: str | None) -> dict:
        key = message_id or f"request-{len(self.data['steps']) + 1}"
        if key not in self.by_message:
            step = {"n": len(self.data["steps"]) + 1, "round": self.round, "tokens": None, "cost": None, "text": [], "tools": []}
            self.data["steps"].append(step)
            self.by_message[key] = step
        return self.by_message[key]

    def stream_event(self, event: dict) -> None:
        """A request's usage arrives in two parts: input and cache tokens when its answer starts,
        the final output count when it ends (assistant messages only carry the first)."""
        if event.get("type") == "message_start":
            message = event.get("message") or {}
            self.streaming = message.get("id")
            if message.get("usage"):
                self.set_tokens(self.step_for(self.streaming), message["usage"])
        elif event.get("type") == "message_delta" and self.streaming and event.get("usage"):
            step = self.step_for(self.streaming)
            step["tokens"] = step["tokens"] or tokens_of(None)
            step["tokens"]["output"] = int(event["usage"].get("output_tokens") or step["tokens"]["output"])
            step["cost"] = round(priced(step["tokens"], self.prices), 5)
            step["final"] = True

    def set_tokens(self, step: dict, usage: dict) -> None:
        step["tokens"] = tokens_of(usage)
        step["cost"] = round(priced(step["tokens"], self.prices), 5)

    def claude_said(self, message, TextBlock, ToolUseBlock) -> None:
        """One of Claude's answers: its text, and the tools it asked for."""
        step = self.step_for(message.message_id)
        if message.usage and not step.get("final"):
            self.set_tokens(step, message.usage)
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                name = block.name.split("__")[-1]
                call = {"tool": name}
                if name == "read_page":
                    call["asked"] = str(block.input.get("page", ""))
                else:
                    call["target"] = block.input.get("page") or f"{block.input.get('wiki', '')}:{block.input.get('new_path', '')}"
                    call["summary"] = block.input.get("summary", "")
                    if block.input.get("edits"):
                        call["edits"] = len(block.input["edits"])
                    if block.input.get("template"):
                        call["template"] = block.input["template"]
                step["tools"].append(call)
                self.tool_calls[block.id] = call
            elif isinstance(block, TextBlock) and block.text.strip():
                step["text"].append(block.text.strip()[:600])

    def tools_answered(self, message, ToolResultBlock) -> None:
        """What our tools sent back to Claude."""
        if not isinstance(message.content, list):
            return
        for block in message.content:
            if not isinstance(block, ToolResultBlock) or block.tool_use_id not in self.tool_calls:
                continue
            content = block.content
            text = content if isinstance(content, str) else "".join(
                part.get("text", "") for part in content or [] if isinstance(part, dict))
            call = self.tool_calls[block.tool_use_id]
            call["resultTokens"] = len(text) // 4  # approximate: what the tool sent back
            if block.is_error:
                call["error"] = text[:300]
            elif call["tool"] == "read_page" and text.startswith("id: "):
                call["page"] = text[4:text.find("\n")] if "\n" in text else text[4:]

    # ---- Endings ----------------------------------------------------------------------------

    def finish(self, ok: bool, message: str, totals: dict | None, cards: list[dict]) -> None:
        self.data.update(finished=datetime.now().isoformat(timespec="seconds"), ok=ok, message=message, totals=totals)
        self.set_cards(cards)
        self.save()

    def set_cards(self, cards: list[dict]) -> None:
        self.data["cards"] = [{k: c.get(k) for k in ("id", "wiki", "kind", "title", "path", "summary", "template")} for c in cards]

    def save(self) -> None:
        (self.run_folder / "transcript.json").write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- Feedback rounds: the same run, continued ------------------------------------------

    def begin_feedback(self, asked: list[tuple[dict, str]], decided: dict[str, str], page_name) -> dict:
        """asked: (card, feedback text) pairs; decided: card id -> "accepted" or "rejected"."""
        entry = {"round": len(self.data["feedback"]) + 1,
                 "cards": [{"card": card["id"], "page": page_name(card), "text": text, "revised": False} for card, text in asked],
                 "accepted": [c for c, how in decided.items() if how == "accepted"],
                 "rejected": [c for c, how in decided.items() if how == "rejected"],
                 "at": datetime.now().isoformat(timespec="seconds"),
                 "firstStep": len(self.data["steps"]) + 1, "reply": "", "revised": False}
        self.data["feedback"].append(entry)
        self.round = entry["round"]
        return entry
