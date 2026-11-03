"""Starts one ingest run, or one feedback round. The agent itself is in agent.py: read that first.

WikiApp starts it as   python run.py <run folder>/job.json
and reads one JSON object per line from its output: progress, cards, and the result.
Everything sent to the agent is saved in the run folder (system.md, first-message.md, log.jsonl),
and transcript.json sums the run up for the app's Past runs list.
Add --prepare-only to build and save the prompts without starting the agent.

   python run.py <run folder>/job.json --feedback <feedback.json>
continues the same run with the reviewer's feedback on some cards ({"cards": [{"card": "c3",
"text": "..."}], "accepted": ["c1"], "rejected": ["c2"]}): one longer conversation, not a new run.

The ingest folder:
  agent.py        the agent: what it's given, and following it until it's done
  tools.py        its two tools: read_page and propose_page
  prompts.py      the text it's given: instructions, first message, feedback message
  agent-prompt.md the instructions themselves
  wikis.py        the wikis: scanning, following [[links]], the index
  transcript.py   the run's record (transcript.json); costs.py its tokens and prices
  progress.py     progress lines for the app, and the run's log
  models.py       the models Claude Code offers, for the app's model menu
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import progress
from agent import ingest_notes, revise_cards


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    feedback_file = argv[argv.index("--feedback") + 1] if "--feedback" in argv[:-1] else None
    args = [a for a in argv if not a.startswith("--") and a != feedback_file]
    if not args:
        print(__doc__)
        return 2
    job_file = Path(args[0]).absolute()
    run_folder = job_file.parent
    job = json.loads(job_file.read_text(encoding="utf-8"))
    progress.open_log(run_folder)
    try:
        if feedback_file:
            feedback = json.loads(Path(feedback_file).read_text(encoding="utf-8"))
            progress.log({"type": "feedback", **feedback})
            return asyncio.run(revise_cards(job, run_folder, feedback))
        return asyncio.run(ingest_notes(job, run_folder, prepare_only="--prepare-only" in argv))
    except Exception as err:  # anything unexpected still ends the run cleanly for the app
        progress.tell_app({"type": "done", "ok": False, "message": f"{type(err).__name__}: {err}"})
        return 1
    finally:
        progress.close_log()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main(sys.argv[1:]))
