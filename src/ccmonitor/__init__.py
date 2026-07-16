"""CCUsageMonitor — a movable desktop overlay for Claude Code usage & limits."""

__version__ = "0.1.0"

# Claude Code version this build was validated against; sent as the User-Agent
# suffix on the usage-API request (a valid claude-code UA is required, see
# docs/04-data-sources.md).
CLAUDE_CODE_UA_VERSION = "2.1.206"
