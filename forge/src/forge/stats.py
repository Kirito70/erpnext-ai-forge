"""Metrics dashboard.

Parses every `audit/<YYYY>/<MM>/forge-audit.jsonl` and produces a summary
report — counts per action / tool, security-score distribution, drift
incidents, escalation rate, recent activity timeline.

Used by:
  - `forge stats` (Markdown report)
  - `forge stats --json` (machine-readable)
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class StatsReport:
    period_start: str | None
    period_end: str | None
    total_entries: int
    actions_by_count: dict[str, int]
    tools_by_count: dict[str, int]
    sync_outcomes: dict[str, int]                 # blocked / live / justified / warned / dry_run / error
    security_scores: dict[str, Any]               # min / max / mean / median / count
    drift_incidents: int
    escalations: int
    recent: list[dict[str, Any]]                  # 10 most recent entries (truncated detail)
    audit_files_scanned: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _iter_audit_entries(repo_root: Path) -> list[dict[str, Any]]:
    """Read every audit JSONL line in the repo. Skips non-parseable lines."""
    entries: list[dict[str, Any]] = []
    audit_root = repo_root / "audit"
    if not audit_root.is_dir():
        return entries
    audit_files = sorted(audit_root.rglob("forge-audit.jsonl"))
    for f in audit_files:
        for line in f.read_text().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _summarize_security_scores(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull per_file_scores from sync entries and compute distribution."""
    all_scores: list[int] = []
    for e in entries:
        scores = e.get("per_file_scores")
        if isinstance(scores, dict):
            for s in scores.values():
                if isinstance(s, (int, float)):
                    all_scores.append(int(s))
    if not all_scores:
        return {"count": 0}
    return {
        "count": len(all_scores),
        "min": min(all_scores),
        "max": max(all_scores),
        "mean": round(statistics.mean(all_scores), 1),
        "median": int(statistics.median(all_scores)),
        "below_block_floor": sum(1 for s in all_scores if s < 80),
        "warn_band": sum(1 for s in all_scores if 80 <= s < 95),
        "auto_accept": sum(1 for s in all_scores if s >= 95),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def collect_stats(
    repo_root: Path,
    since: str | None = None,
) -> StatsReport:
    """Walk audit logs and produce a StatsReport.

    `since` is an ISO-8601 timestamp; entries older are dropped from totals.
    """
    entries = _iter_audit_entries(repo_root)
    if since:
        entries = [e for e in entries if e.get("ts", "") >= since]

    actions: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    sync_outcomes: Counter[str] = Counter()
    drift_incidents = 0
    escalations = 0

    for e in entries:
        action = str(e.get("action", ""))
        actions[action] += 1
        tool = e.get("tool", e.get("tool_or_agent"))
        if tool:
            tools[str(tool)] += 1
        if action.startswith("sync."):
            outcome = action.split(".", 1)[1] if "." in action else "unknown"
            sync_outcomes[outcome] += 1
        if "drift" in action:
            drift_incidents += 1
        if action == "escalation":
            escalations += 1

    sorted_ts = sorted(
        (e.get("ts", "") for e in entries if e.get("ts")),
        reverse=False,
    )
    period_start = sorted_ts[0] if sorted_ts else None
    period_end = sorted_ts[-1] if sorted_ts else None

    # Most recent 10 entries (chronologically newest), abbreviated for table
    recent_sorted = sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)[:10]
    recent: list[dict[str, Any]] = []
    for e in recent_sorted:
        recent.append({
            "ts": e.get("ts", "")[:19],
            "action": e.get("action", ""),
            "tool": e.get("tool", e.get("tool_or_agent", "")),
            "detail": _truncate_detail(e),
        })

    audit_files_scanned = sum(
        1 for _ in (repo_root / "audit").rglob("forge-audit.jsonl")
    ) if (repo_root / "audit").is_dir() else 0

    return StatsReport(
        period_start=period_start,
        period_end=period_end,
        total_entries=len(entries),
        actions_by_count=dict(actions.most_common()),
        tools_by_count=dict(tools.most_common()),
        sync_outcomes=dict(sync_outcomes.most_common()),
        security_scores=_summarize_security_scores(entries),
        drift_incidents=drift_incidents,
        escalations=escalations,
        recent=recent,
        audit_files_scanned=audit_files_scanned,
    )


def _truncate_detail(entry: dict[str, Any]) -> str:
    """Best-effort one-line summary of an entry's non-standard fields."""
    skip = {"ts", "action", "tool", "tool_or_agent", "session_id", "host", "user"}
    parts: list[str] = []
    for k, v in entry.items():
        if k in skip:
            continue
        parts.append(f"{k}={str(v)[:30]}")
        if len(parts) >= 3:
            break
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def render_markdown(report: StatsReport) -> str:
    lines: list[str] = []
    lines.append("# Forge — Audit Stats")
    lines.append("")
    if report.total_entries == 0:
        lines.append("_No audit entries found._")
        return "\n".join(lines)

    lines.append(f"**Period:** {report.period_start} → {report.period_end}")
    lines.append(f"**Total entries:** {report.total_entries}")
    lines.append(f"**Audit files scanned:** {report.audit_files_scanned}")
    lines.append("")

    lines.append("## Sync outcomes")
    lines.append("")
    lines.append("| Outcome | Count |")
    lines.append("|---------|------:|")
    if report.sync_outcomes:
        for k, v in report.sync_outcomes.items():
            lines.append(f"| `sync.{k}` | {v} |")
    else:
        lines.append("| _(no sync entries)_ | 0 |")
    lines.append("")

    lines.append("## Top actions")
    lines.append("")
    lines.append("| Action | Count |")
    lines.append("|--------|------:|")
    for k, v in list(report.actions_by_count.items())[:10]:
        lines.append(f"| `{k}` | {v} |")
    lines.append("")

    if report.tools_by_count:
        lines.append("## Tool / agent invocations")
        lines.append("")
        lines.append("| Tool / Agent | Count |")
        lines.append("|--------------|------:|")
        for k, v in list(report.tools_by_count.items())[:10]:
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    if report.security_scores.get("count", 0) > 0:
        s = report.security_scores
        lines.append("## Security score distribution")
        lines.append("")
        lines.append(f"- **Files scored:** {s['count']}")
        lines.append(f"- **Mean / Median:** {s['mean']} / {s['median']}")
        lines.append(f"- **Min / Max:** {s['min']} / {s['max']}")
        lines.append(f"- **Auto-accept (≥95):** {s['auto_accept']}")
        lines.append(f"- **Warn band (80–94):** {s['warn_band']}")
        lines.append(f"- **Below block floor (<80):** {s['below_block_floor']}")
        lines.append("")

    lines.append("## Governance counters")
    lines.append("")
    lines.append(f"- **Drift incidents:** {report.drift_incidents}")
    lines.append(f"- **Architect escalations:** {report.escalations}")
    lines.append("")

    if report.recent:
        lines.append("## Recent activity (last 10)")
        lines.append("")
        lines.append("| Timestamp | Action | Tool/Agent | Detail |")
        lines.append("|-----------|--------|------------|--------|")
        for r in report.recent:
            lines.append(
                f"| {r['ts']} | `{r['action']}` | {r.get('tool', '')} | {r.get('detail', '')} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: 'X ago' style for the --since CLI flag
# ---------------------------------------------------------------------------
def parse_relative_since(value: str) -> str:
    """Convert a duration ('1h', '7d', '30d') to an ISO-8601 timestamp.

    Falls back to returning the input unchanged if it already looks ISO-like.
    """
    value = value.strip()
    if value.endswith("h") or value.endswith("d") or value.endswith("m"):
        unit = value[-1]
        try:
            n = int(value[:-1])
        except ValueError:
            return value
        delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "m": timedelta(minutes=n)}[unit]
        return (datetime.now(timezone.utc) - delta).isoformat()
    return value
