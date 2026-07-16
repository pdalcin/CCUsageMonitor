# Data Sources (verified 2026-07-12)

Everything here was confirmed by inspecting the live machine, not assumed.

## 1. Local session logs — tokens, cost, model, session time

- **Location:** `~/.claude/projects/<encoded-project-path>/<sessionId>.jsonl`
  - `<encoded-project-path>` = the project's absolute path with separators replaced by `-`
    (e.g. `C:\Projects\CCUsageMonitor` → `C--Projects-CCUsageMonitor`).
- **Format:** JSON Lines. Each line is one record with a `type` field. Observed types:
  `mode`, `permission-mode`, `file-history-snapshot`, `user`, `attachment`,
  `last-prompt`, `ai-title`, `assistant`.
- **What we use:** records of `type == "assistant"` carry `message.usage`:

  ```json
  {
    "input_tokens": 15912,
    "cache_creation_input_tokens": 3029,
    "cache_read_input_tokens": 16092,
    "output_tokens": 2118,
    "service_tier": "standard",
    "cache_creation": { "ephemeral_1h_input_tokens": 3029, "ephemeral_5m_input_tokens": 0 }
  }
  ```

  and `message.model` (e.g. `claude-opus-4-8`). Records carry a `timestamp` (ISO-8601 Z).

- **Current session detection:** the session whose `.jsonl` was **most recently modified**
  under the project dir (or a specific `sessionId` if we launch scoped to one). Session start =
  first record timestamp; "session time" = now − start.
- **Cost:** derived from token counts × per-model pricing (`pricing.py`). Cache-read and
  cache-write tokens are priced differently from fresh input tokens.
- **No auth required.** Pure file reads. This path always works even if the network / API is down.

## 2. Live usage limits — 5-hour + weekly windows

### Primary: `GET https://api.anthropic.com/api/oauth/usage`
Undocumented endpoint that backs Claude Code's `/usage` command. Returns authoritative
window state: utilization for the 5h and 7d windows, reset timestamps, and the plan's limits.

**Required request headers**
- `Authorization: Bearer <accessToken>` — from `~/.claude/.credentials.json`.
- `User-Agent: claude-code/<version>` — **mandatory**. Without a valid CC User-Agent the request
  lands in an aggressively rate-limited bucket and returns persistent `429`s. (Our version string:
  `claude-code/2.1.206`.)
- `Accept: application/json`.

**Credentials file** `~/.claude/.credentials.json`:
```
claudeAiOauth:
  accessToken          "sk-ant-oat01-..."
  refreshToken         "..."
  expiresAt            epoch-ms         # token lifetime ~ hours; may need refresh
  refreshTokenExpiresAt epoch-ms
  scopes               ["user:inference", "user:profile", "user:sessions:claude_code", ...]
  subscriptionType     "pro"
  rateLimitTier        "default_claude_ai"
```

**Rate-limit discipline (critical):** the endpoint 429s hard.
- Poll **no faster than every 180 s**; default to **300 s**.
- Cache the last good response; the UI always renders last-known values with an "as of" age.
- On `429`/error: exponential backoff (cap ~30 min), keep showing cached data dimmed.
- Token may expire (`expiresAt`); on `401` we surface a "re-auth in Claude Code" hint. (Automatic
  refresh via `refreshToken` is a **stretch** item — see plan Phase 6; risky to touch, so v1 just
  detects expiry and degrades.)

### Fallback (not used in v1): unified rate-limit response headers
`anthropic-ratelimit-unified-5h-*` and `-7d-*` headers are returned on normal inference calls
(`utilization` 0..1, `reset` epoch-s, `status`). Reading them requires *making* an inference call,
which costs tokens — so we do **not** use this for polling. Documented here as a known alternative.

## Response-shape TODO
The exact JSON shape of `/api/oauth/usage` is not yet captured on this machine (the endpoint is
undocumented and rate-limited). **Phase 4, Step 1** is a one-shot probe (behind explicit user
consent, since it spends the token's rate-limit budget) to record the real field names into
`docs/samples/oauth-usage.sample.json`, then the parser is written against that. Until then,
`usage_api.py` codes against a *defensive* shape and the app runs fully on local data.

## Privacy note
The OAuth token never leaves the machine except in the single HTTPS request to
`api.anthropic.com` that it is already used for by Claude Code. We read it, we never log it, we
never copy it elsewhere.
