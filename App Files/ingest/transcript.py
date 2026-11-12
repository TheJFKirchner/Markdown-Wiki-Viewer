"""The run's record, transcript.json: each step Claude took with the tools it called and what it
said, the cards, the totals (tokens and cost), and any feedback rounds. The app's Past runs list
shows it. Written when the run ends (also when it fails), and extended by each feedback round.
"""

import json
from datetime import datetime
from pathlib import Path


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
        self.tool_calls = {}
        self.step = None            # the step being filled in
        self.step_answered = False  # our tools have answered it: what Claude does next is a new request
        self.round = 0              # 0: the run itself; 1, 2...: feedback rounds

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

    # ---- What comes back from Claude, step by step ------------------------------------------
    # The engine reports what Claude said and which tools it called, and the tokens and cost once
    # per message (the run, or one round), not per request. A step here is one request as far as
    # it can be seen: it ends when our tools have answered, and Claude's next words or tool calls
    # start the next one. Steps carry no tokens of their own; the turn's are in the totals.

    def current_step(self) -> dict:
        if self.step is None or self.step_answered:
            self.step = {"n": len(self.data["steps"]) + 1, "round": self.round, "tokens": None, "cost": None,
                         "text": [], "tools": []}
            self.data["steps"].append(self.step)
            self.step_answered = False
        return self.step

    def claude_said(self, text: str) -> None:
        """A short remark from Claude."""
        if text.strip():
            self.current_step()["text"].append(text.strip()[:600])

    def tool_called(self, call_id: str, name: str, inputs: dict) -> None:
        """A tool Claude asked for (by its short name: read_page, propose_page, ask_reviewer)."""
        inputs = inputs or {}
        call = {"tool": name}
        if name == "read_page":
            call["asked"] = str(inputs.get("page", ""))
        elif name == "ask_reviewer":
            call["target"] = "questions for the reviewer"   # the run window shows "Proposed <target>"
            call["summary"] = "; ".join(str(q.get("question") or "") for q in inputs.get("questions") or [] if isinstance(q, dict))[:600]
        elif name != "propose_page":
            call["target"] = name   # a tool the agent doesn't have (it is denied: see the call's error)
        else:
            call["target"] = inputs.get("page") or f"{inputs.get('wiki', '')}:{inputs.get('new_path', '')}"
            call["summary"] = inputs.get("summary", "")
            if inputs.get("edits"):
                call["edits"] = len(inputs["edits"])
            if inputs.get("template"):
                call["template"] = inputs["template"]
        self.current_step()["tools"].append(call)
        self.tool_calls[call_id] = call

    def tool_answered(self, call_id: str, text: str, is_error: bool) -> None:
        """What our tool sent back to Claude."""
        if self.step is not None:
            self.step_answered = True
        call = self.tool_calls.get(call_id)
        if call is None:
            return
        text = text or ""
        call["resultTokens"] = len(text) // 4  # approximate: what the tool sent back
        if is_error:
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
