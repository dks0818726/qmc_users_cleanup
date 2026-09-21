"""Inactivity classification logic for QRS users.

Qlik's /qrs/user API can expose a native `inactive` field, depending on the
environment and API version. This module supports four
pluggable strategies, selected via the INACTIVITY_STRATEGY env var:

  - inactive        : QRS's native `inactive` boolean field
  - custom_property : a Custom Property (tag-like key/value) on the user
  - blacklisted     : QRS's own `blacklisted` boolean field
  - external_audit  : an external CSV of last-login dates; users not seen
                      within N days are considered inactive

Run `cleanup.py --inspect` against a real environment first to confirm which
signal is actually populated for your users before relying on this.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InactiveCandidate:
    user_id: str
    user_directory: str
    user_name: str
    reason: str
    blacklisted: bool | None = None

    @property
    def full_id(self) -> str:
        return f"{self.user_directory}\\{self.user_name}"


def _get_custom_property_value(user: dict[str, Any], property_name: str) -> str | None:
    for cp in user.get("customProperties", []) or []:
        definition = cp.get("definition", {}) or {}
        if definition.get("name") == property_name:
            return cp.get("value")
    return None


def _load_audit_last_seen(csv_path: str) -> dict[str, datetime]:
    """Load an external audit CSV with columns: userDirectory,userId,lastSeen (ISO date)."""
    last_seen: dict[str, datetime] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = f"{row['userDirectory']}\\{row['userId']}".lower()
            try:
                last_seen[key] = datetime.fromisoformat(row["lastSeen"])
            except (KeyError, ValueError):
                continue
    return last_seen


def classify_inactive_users(
    users: list[dict[str, Any]],
    strategy: str,
    *,
    custom_property_name: str = "inactive",
    custom_property_value: str = "True",
    audit_csv_path: str | None = None,
    audit_days_threshold: int = 90,
) -> list[InactiveCandidate]:
    """Return the list of users considered inactive under the chosen strategy."""
    candidates: list[InactiveCandidate] = []

    if strategy == "inactive":
        for user in users:
            if user.get("inactive") is True:
                candidates.append(
                    InactiveCandidate(
                        user_id=user.get("id", ""),
                        user_directory=user.get("userDirectory", ""),
                        user_name=user.get("userId", ""),
                        reason="QRS 'inactive' flag is true",
                        blacklisted=user.get("blacklisted"),
                    )
                )

    elif strategy == "custom_property":
        for user in users:
            value = _get_custom_property_value(user, custom_property_name)
            if value is not None and str(value).strip().lower() == custom_property_value.strip().lower():
                candidates.append(
                    InactiveCandidate(
                        user_id=user.get("id", ""),
                        user_directory=user.get("userDirectory", ""),
                        user_name=user.get("userId", ""),
                        reason=f"Custom property '{custom_property_name}' = '{value}'",
                        blacklisted=user.get("blacklisted"),
                    )
                )

    elif strategy == "blacklisted":
        for user in users:
            if user.get("blacklisted") is True:
                candidates.append(
                    InactiveCandidate(
                        user_id=user.get("id", ""),
                        user_directory=user.get("userDirectory", ""),
                        user_name=user.get("userId", ""),
                        reason="QRS 'blacklisted' flag is true",
                        blacklisted=user.get("blacklisted"),
                    )
                )

    elif strategy == "external_audit":
        if not audit_csv_path:
            raise ValueError("INACTIVE_AUDIT_CSV_PATH must be set for the external_audit strategy")
        last_seen = _load_audit_last_seen(audit_csv_path)
        cutoff = datetime.now() - timedelta(days=audit_days_threshold)
        for user in users:
            key = f"{user.get('userDirectory', '')}\\{user.get('userId', '')}".lower()
            seen_at = last_seen.get(key)
            if seen_at is None or seen_at < cutoff:
                reason = (
                    "No audit record found (never seen)"
                    if seen_at is None
                    else f"Last seen {seen_at.date()} (older than {audit_days_threshold} days)"
                )
                candidates.append(
                    InactiveCandidate(
                        user_id=user.get("id", ""),
                        user_directory=user.get("userDirectory", ""),
                        user_name=user.get("userId", ""),
                        reason=reason,
                        blacklisted=user.get("blacklisted"),
                    )
                )

    else:
        raise ValueError(f"Unknown INACTIVITY_STRATEGY: {strategy}")

    return candidates
