"""Read-only access to Claude Code's stored OAuth token.

Claude Code normally stores the token as JSON at ``~/.claude/.credentials.json``,
but the location varies: users can relocate the whole config dir with the
``CLAUDE_CONFIG_DIR`` environment variable, and some installs live under a
different home/APPDATA layout. We therefore search a list of candidate paths (and
honour a user-supplied override) rather than assuming a single fixed file.

The token is never logged, copied, or written back — this module only ever
*reads*.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# Anthropic OAuth *access* tokens are self-identifying, so we can recognise one
# in an unknown store without knowing its schema. (oat01 = access; ort01 =
# refresh — we deliberately only accept access tokens.)
_OAT_RE = re.compile(r"sk-ant-oat01-[A-Za-z0-9_\-]+")

# Kept for backwards-compat / documentation: the default, most common location.
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class Credentials:
    access_token: str
    expires_at_ms: int | None
    subscription_type: str | None
    rate_limit_tier: str | None
    source_path: Path | None = None  # where we actually found it (for diagnostics)
    is_omp: bool = False             # sourced from OMP/oh-my-pi, not Claude Code

    @property
    def is_expired(self) -> bool:
        if not self.expires_at_ms:
            return False
        return time.time() * 1000 >= self.expires_at_ms


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def credentials_search_paths(override: str | None = None) -> list[Path]:
    """Ordered list of places to look for ``.credentials.json``.

    A user-supplied ``override`` wins, then ``CLAUDE_CONFIG_DIR``, then the usual
    home/APPDATA locations. Used both to load credentials and to tell the user
    *where* we looked when we can't find them.
    """
    paths: list[Path] = []
    if override:
        paths.append(Path(override).expanduser())

    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        # CLAUDE_CONFIG_DIR may point at the dir, or (rarely) the file itself.
        p = Path(env_dir).expanduser()
        paths.append(p if p.name == ".credentials.json" else p / ".credentials.json")

    paths.append(Path.home() / ".claude" / ".credentials.json")

    for env in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / "claude" / ".credentials.json")
            paths.append(Path(base) / "Claude" / ".credentials.json")

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        paths.append(Path(userprofile) / ".claude" / ".credentials.json")

    return _dedupe(paths)


def _try_load(path: Path) -> Credentials | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not token:
        return None
    return Credentials(
        access_token=token,
        expires_at_ms=oauth.get("expiresAt"),
        subscription_type=oauth.get("subscriptionType"),
        rate_limit_tier=oauth.get("rateLimitTier"),
        source_path=path,
    )


def load_credentials_from(path: str | Path) -> Credentials | None:
    """Load credentials from exactly one file, ignoring any fallback. Used to
    validate a user-chosen ``.credentials.json`` regardless of expiry/OMP."""
    return _try_load(Path(path).expanduser())


def _load_claude_code(override: str | None) -> Credentials | None:
    """First credentials found in Claude Code's own credential files, or None."""
    for path in credentials_search_paths(override):
        creds = _try_load(path)
        if creds is not None:
            return creds
    return None


def load_credentials(
    override: str | None = None, priority: str = "claude_code"
) -> Credentials | None:
    """Return the first usable credentials found, or None. Never raises.

    ``priority`` controls the search order between Claude Code's own credential
    files and the experimental OMP/oh-my-pi fallback:

      * ``"claude_code"`` (default): Claude Code first. If none is found, fall back
        to OMP. If a Claude Code token *is* found but has **expired**, also check
        OMP and prefer a non-expired OMP token when one exists.
      * ``"omp"`` (experimental): OMP first; fall back to Claude Code's files.
    """
    if priority == "omp":
        omp = load_omp_credentials()
        if omp is not None:
            return omp
        return _load_claude_code(override)

    cc = _load_claude_code(override)
    if cc is None:
        return load_omp_credentials()
    if cc.is_expired:
        # Claude Code's saved login is stale — try OMP as a fallback and prefer it
        # only if it actually offers a non-expired token.
        omp = load_omp_credentials()
        if omp is not None and not omp.is_expired:
            return omp
    return cc


# ---------------------------------------------------------------------------
# OMP / oh-my-pi fallback  (https://omp.sh)
#
# OMP is a *separate* coding agent that stores every provider credential in a
# local SQLite DB (~/.omp/agent/agent.db, or under $PI_CONFIG_DIR) rather than
# Claude Code's ~/.claude/.credentials.json. The exact schema is versioned and
# undocumented, so instead of assuming table/column names we open the DB
# READ-ONLY and scan every cell for an Anthropic OAuth access token. If the
# payload is encrypted (no recognisable token), we simply find nothing.
#
# NOTE: developed without OMP installed on the dev machine — the token-shape and
# read path are best-effort and want validation by a real OMP user.
# ---------------------------------------------------------------------------
def omp_db_paths() -> list[Path]:
    """Candidate locations of OMP's auth SQLite database."""
    paths: list[Path] = []
    cfg = os.environ.get("PI_CONFIG_DIR")
    if cfg:
        base = Path(cfg).expanduser()
        paths += [base / "agent" / "agent.db", base / "agent.db"]
    home = Path.home()
    paths += [home / ".omp" / "agent" / "agent.db", home / ".omp" / "agent.db"]
    return _dedupe(paths)


def _first_value(obj, keys: set[str]):
    """Breadth-first search a parsed-JSON structure for the first value under any
    of ``keys`` (used to recover expiry/subscription that sit near the token)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keys and isinstance(v, (int, str)):
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _extract_token_fields(text: str) -> dict | None:
    m = _OAT_RE.search(text)
    if not m:
        return None
    token = m.group(0)
    expires_at_ms = None
    subscription_type = None
    try:  # if the cell is JSON, opportunistically recover metadata
        obj = json.loads(text)
        exp = _first_value(obj, {"expiresAt", "expires_at", "expiresAtMs"})
        if isinstance(exp, int):
            expires_at_ms = exp
        subscription_type = _first_value(obj, {"subscriptionType", "subscription_type"})
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {
        "token": token,
        "expires_at_ms": expires_at_ms,
        "subscription_type": subscription_type,
    }


def _scan_sqlite_for_token(con: sqlite3.Connection) -> dict | None:
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    for table in tables:
        try:
            cur.execute(f'SELECT * FROM "{table}"')
            rows = cur.fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            for cell in row:
                if isinstance(cell, bytes):
                    cell = cell.decode("utf-8", "ignore")
                if not isinstance(cell, str) or "sk-ant-oat01-" not in cell:
                    continue
                fields = _extract_token_fields(cell)
                if fields:
                    return fields
    return None


def _read_omp_db(db: Path) -> Credentials | None:
    # Open strictly read-only. Try a plain RO open first (respects locks); if the
    # DB is locked by a running OMP, retry as immutable to bypass locking. We only
    # ever read — never write, never migrate.
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(db.as_uri() + suffix, uri=True, timeout=1.0)
        except sqlite3.Error:
            continue
        try:
            fields = _scan_sqlite_for_token(con)
        except sqlite3.Error:
            fields = None
        finally:
            con.close()
        if fields:
            return Credentials(
                access_token=fields["token"],
                expires_at_ms=fields["expires_at_ms"],
                subscription_type=fields["subscription_type"],
                rate_limit_tier=None,
                source_path=db,
                is_omp=True,
            )
    return None


def load_omp_credentials() -> Credentials | None:
    """Best-effort: recover a Claude OAuth access token from OMP's SQLite store.
    Read-only; returns None if OMP isn't present or no token can be recovered."""
    for db in omp_db_paths():
        try:
            if not db.exists():
                continue
        except OSError:
            continue
        creds = _read_omp_db(db)
        if creds is not None:
            return creds
    return None
