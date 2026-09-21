"""CLI entrypoint for the standalone QMC inactive-user cleanup tool.

Usage:
    python cleanup.py --inspect
        Fetch users and print the raw field names/custom properties seen,
        to help decide which INACTIVITY_STRATEGY applies to your environment.
        Makes NO changes.

    python cleanup.py --dry-run                 (default if no mode given)
        Fetch + classify inactive users, write a report to REPORTS_DIR,
        delete nothing.

    python cleanup.py --confirm-delete --yes
        Re-run classification and actually delete each candidate via QRS,
        logging per-user results. Requires --yes as an explicit safety gate.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from inactive_users import classify_inactive_users
from qrs_client import QrsClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup")


def load_config() -> dict:
    load_dotenv()
    return {
        "base_url": os.environ["QRS_BASE_URL"],
        "qlik_user": os.environ["QRS_USER"],
        "xrf_key": os.environ["QRS_XRF_KEY"],
        "verify_ssl": os.environ.get("QRS_VERIFY_SSL", "false").lower() == "true",
        "timeout_seconds": int(os.environ.get("QRS_TIMEOUT_SECONDS", "30")),
        "strategy": os.environ.get("INACTIVITY_STRATEGY", "custom_property"),
        "custom_property_name": os.environ.get("INACTIVE_CUSTOM_PROPERTY_NAME", "Inactive"),
        "custom_property_value": os.environ.get("INACTIVE_CUSTOM_PROPERTY_VALUE", "true"),
        "audit_csv_path": os.environ.get("INACTIVE_AUDIT_CSV_PATH") or None,
        "audit_days_threshold": int(os.environ.get("INACTIVE_AUDIT_DAYS_THRESHOLD", "90")),
        "protected_users": {
            u.strip().lower()
            for u in os.environ.get("PROTECTED_USERS", "").split(",")
            if u.strip()
        },
        "reports_dir": os.environ.get("REPORTS_DIR", "reports"),
    }


def build_client(cfg: dict) -> QrsClient:
    return QrsClient(
        base_url=cfg["base_url"],
        qlik_user=cfg["qlik_user"],
        xrf_key=cfg["xrf_key"],
        verify_ssl=cfg["verify_ssl"],
        timeout_seconds=cfg["timeout_seconds"],
    )


def fetch_users_for_strategy(client: QrsClient, strategy: str) -> list[dict]:
    if strategy == "inactive":
        return client.fetch_users(filter_expr="inactive eq true")
    if strategy == "blacklisted":
        return client.fetch_users(filter_expr="blacklisted eq true")
    return client.fetch_users()


def cmd_inspect(cfg: dict) -> None:
    client = build_client(cfg)
    users = client.fetch_users()
    logger.info("Fetched %d users from QRS.", len(users))
    if not users:
        return
    sample = users[0]
    sample1 = users[1] if len(users) > 1 else None
    logger.info("Top-level fields on a user record: %s", sample.keys())
    if sample1:
        logger.info("Top-level fields on the second user record: %s", sample1.values())
    cp_names = set()
    for u in users:
        for cp in u.get("customProperties", []) or []:
            name = (cp.get("definition") or {}).get("name")
            if name:
                cp_names.add(name)
    logger.info("Custom property names seen across all users: %s", sorted(cp_names) or "(none)")
    blacklisted_count = sum(1 for u in users if u.get("blacklisted") is True)
    logger.info("Users with blacklisted=true: %d", blacklisted_count)
    logger.info(
        "Use this output to choose INACTIVITY_STRATEGY and its settings in .env, "
        "then re-run with --dry-run."
    )


def _filter_protected(candidates, protected_users: set[str]):
    kept, skipped = [], []
    for c in candidates:
        if c.full_id.lower() in protected_users or c.user_name.lower() in protected_users:
            skipped.append(c)
        else:
            kept.append(c)
    return kept, skipped


def _write_report(cfg: dict, candidates, deleted: bool) -> str:
    os.makedirs(cfg["reports_dir"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "deleted" if deleted else "dry_run"
    path = os.path.join(cfg["reports_dir"], f"inactive_users_{suffix}_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["userId", "userDirectory", "userName", "inactive", "blacklisted", "reason", "deleted"]
        )
        for c in candidates:
            writer.writerow(
                [c.user_id, c.user_directory, c.user_name, True, c.blacklisted, c.reason, deleted]
            )
    return path


def cmd_dry_run(cfg: dict) -> None:
    client = build_client(cfg)
    users = fetch_users_for_strategy(client, cfg["strategy"])
    logger.info("Fetched %d relevant user(s) from QRS.", len(users))
    candidates = classify_inactive_users(
        users,
        strategy=cfg["strategy"],
        custom_property_name=cfg["custom_property_name"],
        custom_property_value=cfg["custom_property_value"],
        audit_csv_path=cfg["audit_csv_path"],
        audit_days_threshold=cfg["audit_days_threshold"],
    )
    kept, skipped = _filter_protected(candidates, cfg["protected_users"])
    report_path = _write_report(cfg, kept, deleted=False)
    logger.info(
        "DRY RUN: %d inactive candidate(s), %d protected/skipped. Report: %s",
        len(kept), len(skipped), report_path,
    )
    if skipped:
        logger.info("Protected users excluded from deletion: %s", [s.full_id for s in skipped])
    logger.info("No users were deleted. Re-run with --confirm-delete --yes to delete these.")


def cmd_confirm_delete(cfg: dict, auto_yes: bool) -> None:
    client = build_client(cfg)
    users = fetch_users_for_strategy(client, cfg["strategy"])
    candidates = classify_inactive_users(
        users,
        strategy=cfg["strategy"],
        custom_property_name=cfg["custom_property_name"],
        custom_property_value=cfg["custom_property_value"],
        audit_csv_path=cfg["audit_csv_path"],
        audit_days_threshold=cfg["audit_days_threshold"],
    )
    kept, skipped = _filter_protected(candidates, cfg["protected_users"])

    if not kept:
        logger.info("No inactive candidates to delete (after protected-user filtering).")
        return

    logger.warning("About to DELETE %d user(s):", len(kept))
    for c in kept:
        logger.warning("  - %s (%s)", c.full_id, c.reason)

    if not auto_yes:
        answer = input(f"Type YES to permanently delete these {len(kept)} user(s): ")
        if answer.strip() != "YES":
            logger.info("Aborted — no changes made.")
            return

    results = []
    for c in kept:
        try:
            client.delete_user(c.user_id)
            logger.info("Deleted %s", c.full_id)
            results.append((c, True, ""))
        except Exception as exc:  # noqa: BLE001 - log and continue with remaining users
            logger.error("Failed to delete %s: %s", c.full_id, exc)
            results.append((c, False, str(exc)))

    os.makedirs(cfg["reports_dir"], exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(cfg["reports_dir"], f"inactive_users_delete_results_{ts}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            [
                {
                    "userId": c.user_id,
                    "userDirectory": c.user_directory,
                    "userName": c.user_name,
                    "inactive": True,
                    "blacklisted": c.blacklisted,
                    "reason": c.reason,
                    "deleted": ok,
                    "error": err,
                }
                for c, ok, err in results
            ],
            fh,
            indent=2,
        )
    succeeded = sum(1 for _, ok, _ in results if ok)
    logger.info("Deletion complete: %d/%d succeeded. Results: %s", succeeded, len(results), path)


def main() -> int:
    parser = argparse.ArgumentParser(description="QMC inactive-user cleanup tool")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true", help="Inspect real user payloads; no changes.")
    mode.add_argument("--dry-run", action="store_true", help="Classify + report only (default).")
    mode.add_argument("--confirm-delete", action="store_true", help="Actually delete inactive users.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive YES prompt (non-interactive runs).")
    args = parser.parse_args()

    cfg = load_config()

    if args.inspect:
        cmd_inspect(cfg)
    elif args.confirm_delete:
        cmd_confirm_delete(cfg, auto_yes=args.yes)
    else:
        cmd_dry_run(cfg)

    return 0


if __name__ == "__main__":
    sys.exit(main())
