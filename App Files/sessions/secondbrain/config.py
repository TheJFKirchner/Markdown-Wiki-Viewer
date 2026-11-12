"""Tool configuration: where the wikis and transcripts live, and which models to use.

Paths not set in config.json come from WikiApp's path list (host/pathlist.py): the transcripts
folder ("transcripts", by default Claude Code's ~/.claude/projects) and where config.json itself
is ("sessions_config", by default beside sb.py; SECOND_BRAIN_CONFIG overrides it).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_HOST = str(ROOT.parent / "host")
if _HOST not in sys.path:
    sys.path.append(_HOST)
import pathlist  # noqa: E402  (standard library only, like this package)

DEFAULTS = {
    "personal_wiki": "",
    "team_wiki": "",
    "transcripts_dir": "",   # empty: the path list's "transcripts" entry
    # The engine agentlib runs the requests on: empty for the app's engine settings (engine.json),
    # "fake" in tests. claude_cmd and claude_extra_args are no longer used (requests go through
    # agentlib, not the claude command); they are still accepted so an older config.json loads.
    "engine": "",
    "claude_cmd": "claude",
    "claude_extra_args": ["--strict-mcp-config"],
    # By exact id, not alias: an older Claude Code takes `haiku` to mean Haiku 4.5, at ten times the price.
    # Not set in config.json: the model the app's engine settings give the agent (see Config).
    "extract_model": "claude-haiku-5-5",
    "review_model": "claude-sonnet-5-5",
    "capture_thinking": False,
    "review_thinking": True,
    "lookback_days": 14,
    "review_after_entries": 3,
    "folder_after_topics": 3,
    # The Sessions list hides sessions with fewer of the person's own messages than this, on the
    # command line on its own. With WikiApp's private folder the app's filter decides instead
    # (pathlist.get_sessions_filter, default 3; 0 = off). min_user_messages is the older name,
    # still read when min_turns isn't set.
    "min_turns": None,
    "min_user_messages": 2,
    "max_transcript_chars": 160000,
    "llm_timeout_seconds": 300,
    "exclude_project_patterns": [],
}


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, values: dict, path: Path | None):
        self.path = path
        self._given = set(values)
        for key, default in DEFAULTS.items():
            setattr(self, key, values.get(key, default))
        unknown = sorted(set(values) - set(DEFAULTS))
        if unknown:
            raise ConfigError(f"Unknown config keys: {', '.join(unknown)}")
        # The models the app's engine settings give the two agents, unless config.json names one.
        try:
            settings = pathlist.get_engine_settings()
            models = (settings["engines"].get(self.engine or settings["engine"]) or {}).get("models") or {}
        except Exception:  # no private folder, or an unreadable engine.json: the defaults above
            models = {}
        for key, agent in (("extract_model", "executive-assistant"), ("review_model", "wiki-reviewer")):
            if key not in values and isinstance(models.get(agent), str) and models[agent]:
                setattr(self, key, models[agent])

    def hide_below(self) -> int:
        """Sessions with fewer of the person's own messages than this are left out of the list
        (0: none are). With WikiApp's private folder: exactly what the app shows
        (pathlist.get_sessions_filter: the stored filter, else 3); config.json isn't consulted, so
        the two always agree. On the command line on its own: config.json's min_turns, else its
        older min_user_messages, else 3."""
        try:
            if pathlist.app_folder() is not None:
                return pathlist.get_sessions_filter()["min_turns"]
        except Exception:  # an unreadable private folder: as on the command line on its own
            pass
        if isinstance(self.min_turns, int) and not isinstance(self.min_turns, bool):
            return max(0, self.min_turns)
        if "min_user_messages" in self._given and isinstance(self.min_user_messages, int):
            return max(0, self.min_user_messages)
        return pathlist.DEFAULT_MIN_TURNS

    @staticmethod
    def _dir(value: str) -> Path | None:
        return Path(os.path.expandvars(value)).expanduser() if value else None

    @property
    def personal(self) -> Path:
        p = self._dir(self.personal_wiki)
        if p is None:
            raise ConfigError("personal_wiki is not set in config.json")
        return p

    @property
    def team(self) -> Path | None:
        return self._dir(self.team_wiki)

    @property
    def transcripts(self) -> Path:
        return self._dir(self.transcripts_dir) or pathlist.path("transcripts")


def load(path: str | None = None, overrides: dict | None = None) -> Config:
    """Load config from --config, $SECOND_BRAIN_CONFIG, or the path list's "sessions_config"
    (config.json beside sb.py unless the app points it elsewhere).

    overrides (from --personal and --team) win over the file. With a personal wiki given
    that way, the file is optional: this is how the wiki app calls the tool.
    """
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    explicit = path or os.environ.get("SECOND_BRAIN_CONFIG")
    p = Path(explicit or str(pathlist.path("sessions_config") or ROOT / "config.json")).expanduser()
    if p.exists():
        try:
            values = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{p} is not valid JSON: {e}") from e
    elif explicit or not overrides.get("personal_wiki"):
        raise ConfigError(
            f"Config not found at {p}. Copy config.example.json to config.json and set personal_wiki, or pass --personal."
        )
    else:
        values, p = {}, None
    values.update(overrides)
    return Config(values, p)
