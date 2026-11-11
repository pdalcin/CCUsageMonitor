"""Read Claude Code's local session logs to compute live token usage & cost.

Claude Code writes one JSONL file per session under
``~/.claude/projects/<encoded-project-path>/<sessionId>.jsonl``. Each assistant
turn is a record of ``type == "assistant"`` whose ``message.usage`` holds the
token counts and ``message.model`` the model id. We sum those per model, so a
session that switched models is costed correctly.

Each assistant record also carries the reasoning ``effort`` the turn ran at
(``perTurnEffort`` when set per turn, else the session ``effort``); the latest one
wins, falling back to ``effortLevel`` in ``~/.claude/settings.json``.

Logs only ever grow, so parses are cached per file and resumed from the last byte
read: a busy multi-MB session costs only its new lines on each 2 s poll.

No authentication and no network: this always works while Claude Code is used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import pricing

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def encode_project_path(project_path: str | Path) -> str:
    """Replicate Claude Code's project-dir encoding (path separators -> '-').

    e.g. ``C:\\Projects\\CCUsageMonitor`` -> ``C--Projects-CCUsageMonitor``.
    """
    s = str(project_path)
    for sep in ("\\", "/", ":"):
        s = s.replace(sep, "-")
    return s


@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, usage: dict) -> None:
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        self.cache_creation_tokens += int(usage.get("cache_creation_input_tokens", 0) or 0)
        self.cache_read_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass
class SessionStats:
    session_id: str | None = None
    project_path: str | None = None
    per_model: dict[str, ModelUsage] = field(default_factory=dict)
    primary_model: str | None = None       # most-recently-seen assistant model
    effort: str | None = None               # reasoning effort of the latest turn
    message_count: int = 0                  # assistant turns
    started_at: datetime | None = None
    last_activity_at: datetime | None = None

    @property
    def total_tokens(self) -> int:
        return sum(u.total for u in self.per_model.values())

    @property
    def estimated_cost(self) -> float:
        total = 0.0
        for model, u in self.per_model.items():
            total += pricing.cost(
                model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_creation_tokens=u.cache_creation_tokens,
                cache_read_tokens=u.cache_read_tokens,
            ).total
        return total

    @property
    def cost_is_complete(self) -> bool:
        """True only if every model in the session has a known price."""
        return all(pricing.cost(m).known for m in self.per_model) if self.per_model else True

    @property
    def session_duration_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.last_activity_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())


def _parse_ts(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_current_session_file(
    project_path: str | Path | None = None,
) -> Path | None:
    """Return the JSONL of the most recently modified session.

    If ``project_path`` is given, search only that project's dir; otherwise search
    all projects and pick the newest session file overall.
    """
    if project_path is not None:
        search_dirs = [CLAUDE_PROJECTS_DIR / encode_project_path(project_path)]
    else:
        if not CLAUDE_PROJECTS_DIR.is_dir():
            return None
        search_dirs = [p for p in CLAUDE_PROJECTS_DIR.iterdir() if p.is_dir()]

    newest: Path | None = None
    newest_mtime = -1.0
    for d in search_dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime, newest = mtime, f
    return newest


def default_effort(model: str | None = None) -> str | None:
    """The configured effort from Claude Code's settings (per-model first), used
    when a session hasn't logged a turn yet."""
    try:
        data = json.loads(CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    per_model = data.get("modelSettings")
    if model and isinstance(per_model, dict):
        entry = per_model.get(model)
        if isinstance(entry, dict) and entry.get("effortLevel"):
            return str(entry["effortLevel"])
    level = data.get("effortLevel")
    return str(level) if level else None


def _apply_record(stats: SessionStats, rec: dict) -> None:
    ts = _parse_ts(rec.get("timestamp"))
    if ts:
        if stats.started_at is None or ts < stats.started_at:
            stats.started_at = ts
        if stats.last_activity_at is None or ts > stats.last_activity_at:
            stats.last_activity_at = ts

    if rec.get("type") != "assistant":
        return
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return
    usage = msg.get("usage")
    model = msg.get("model")
    if isinstance(usage, dict) and model:
        stats.per_model.setdefault(model, ModelUsage()).add(usage)
        stats.primary_model = model  # last assistant model wins
        stats.message_count += 1
    effort = rec.get("perTurnEffort") or rec.get("effort")
    if isinstance(effort, str) and effort:
        stats.effort = effort


# path -> (bytes consumed, stats so far). Resumed on growth, reset on shrink.
_cache: dict[Path, tuple[int, SessionStats]] = {}


def read_session(path: Path) -> SessionStats:
    """Parse one session JSONL into aggregated stats. Tolerant of bad lines.

    Incremental: only bytes appended since the previous call are parsed. A trailing
    line without its newline (mid-write) is left for the next call. Returns a copy,
    so callers can't disturb the cached running totals."""
    offset, stats = _cache.get(path, (0, None))
    try:
        size = path.stat().st_size
    except OSError:
        return SessionStats(session_id=path.stem, project_path=path.parent.name)
    if stats is None or size < offset:  # new file, or rewritten/truncated
        offset = 0
        stats = SessionStats(session_id=path.stem, project_path=path.parent.name)

    if size > offset:
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read(size - offset)
        except OSError:
            chunk = b""
        end = chunk.rfind(b"\n") + 1  # only complete lines
        for raw in chunk[:end].splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(rec, dict):
                _apply_record(stats, rec)
        offset += end

    _cache[path] = (offset, stats)
    return _copy(stats)


def _copy(stats: SessionStats) -> SessionStats:
    out = replace(stats)
    out.per_model = {m: replace(u) for m, u in stats.per_model.items()}
    return out


def read_current_session(project_path: str | Path | None = None) -> SessionStats | None:
    """Convenience: locate + parse the current session in one call."""
    f = find_current_session_file(project_path)
    if f is None:
        return None
    return read_session(f)
