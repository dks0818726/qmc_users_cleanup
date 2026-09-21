# QMC Inactive-User Cleanup Tool

A small, **standalone** command-line tool to find and delete inactive users
from Qlik Sense via the QRS (Qlik Repository Service) API.

> **This is a fully independent side project.** It does not import from, or
> depend on, the `qlik_lineage` repository in any way. It has its own `.env`,
> its own minimal QRS client, and its own CLI. Safe to copy elsewhere or
> delete without affecting the lineage agent.

## Why this exists

Qlik's `/qrs/user` API may expose a native `inactive` boolean, depending on
the environment and API version. Otherwise, inactivity can be inferred from
other configured signals:

- QRS's native **`inactive = true`** field
- a **Custom Property** on the user (e.g. `Inactive = true`)
- QRS's own `blacklisted` boolean field
- an **external audit log/CSV** of last-login dates (not tracked by QRS itself)

This tool supports all three via a pluggable `INACTIVITY_STRATEGY` setting, and
includes an `--inspect` mode to help you figure out which one applies to your
environment before you rely on it.

## Setup

```powershell
cd C:\Users\DKS0818726\Downloads\qmc_user_cleanup
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env: QRS_BASE_URL, QRS_USER, QRS_XRF_KEY, INACTIVITY_STRATEGY, PROTECTED_USERS
```

Auth follows the same `/custom` virtual-proxy header pattern used elsewhere in
this org (`X-Qlik-Xrfkey` + `X-Qlik-User`) — no NTLM, no direct QRS port 4242,
no client certificates.

## Step 1 — Inspect (find out how inactivity is actually recorded)

```powershell
python cleanup.py --inspect
```

Prints:
- every top-level field on a sample user record
- every Custom Property **name** seen across all users
- how many users have `blacklisted = true`

Use this to decide `INACTIVITY_STRATEGY` and its settings in `.env`. Makes
**no changes**.

## Step 2 — Dry run (default; always do this before deleting)

```powershell
python cleanup.py --dry-run
```

For the `inactive` and `blacklisted` strategies, QRS filters the records
server-side (avoiding the slow full-user collection). The tool then
classifies candidates, excludes anything listed in `PROTECTED_USERS`, and
writes a CSV report to `reports/inactive_users_dry_run_<timestamp>.csv`
with columns: `userId, userDirectory, userName, inactive, blacklisted, reason,
deleted`.
**No deletions happen in this mode.**

## Step 3 — Confirm and delete

```powershell
python cleanup.py --confirm-delete
```

Re-classifies, prints the exact list of users to be deleted, and requires you
to type `YES` to proceed. For non-interactive/automated runs, pass `--yes` to
skip the prompt (use with care):

```powershell
python cleanup.py --confirm-delete --yes
```

Deletion results (success/failure per user) are written to
`reports/inactive_users_delete_results_<timestamp>.json`.

## Safety features

- **Protected users**: anything in the `PROTECTED_USERS` env var (comma
  separated `Directory\UserId` or bare `UserId`) is always excluded from
  deletion, even if flagged inactive.
- **Two-step confirmation**: dry-run report first, explicit `YES`/`--yes`
  required to actually delete.
- **Per-user error handling**: if deleting one user fails, the tool logs the
  error and continues with the rest, then reports a final success/fail count.

## Running tests (mocked, no live Qlik needed)

```powershell
python tests\test_inactive_users.py
```

## Files

| File | Purpose |
|---|---|
| `qrs_client.py` | Minimal QRS client — `fetch_users()`, `delete_user()` |
| `inactive_users.py` | Pluggable inactivity classification strategies |
| `cleanup.py` | CLI entrypoint (`--inspect`, `--dry-run`, `--confirm-delete`) |
| `tests/test_inactive_users.py` | Mocked unit tests for classification logic |
| `.env.example` | Configuration template |
| `reports/` | Generated CSV/JSON reports (gitignored) |
