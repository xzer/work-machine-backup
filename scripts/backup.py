#!/usr/bin/env python3
"""Backup script: syncs files per backup-config.json, commits, bundles."""

import argparse
from datetime import date, datetime, timedelta
import glob as globmod
import logging
import re
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse

log = logging.getLogger("backup")


def setup_logging(backup_repo):
    """Set up logging to both terminal and per-run log file under __log__/."""
    log_dir = os.path.join(backup_repo, "__log__")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"{timestamp}.log")

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                  datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))

    log.setLevel(logging.DEBUG)
    log.addHandler(file_handler)
    log.addHandler(stream_handler)

    log.info(f"Log file: {log_file}")

    # Keep only the most recent 100 log files
    logs = sorted(globmod.glob(os.path.join(log_dir, "*.log")))
    for old in logs[:-100]:
        os.remove(old)

    return log_file


def notify_telegram(telegram_config, message):
    """Send a notification via Telegram bot. Fails silently with a log warning."""
    token = telegram_config.get("botToken", "")
    chat_id = telegram_config.get("chatId", "")
    if not token or not chat_id:
        log.debug("Telegram not configured (missing botToken or chatId), skipping notification")
        return
    try:
        params = urllib.parse.urlencode({"chat_id": chat_id, "text": message})
        url = f"https://api.telegram.org/bot{token}/sendMessage?{params}"
        urllib.request.urlopen(url, timeout=10)
        log.debug("Telegram notification sent")
    except Exception as e:
        log.warning(f"Failed to send Telegram notification: {e}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync configured files into the backup repo, commit, and bundle."
    )
    parser.add_argument(
        "backup_repo",
        help="Path to the backup repository (e.g. ~/work-backup)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--notify-test",
        action="store_true",
        help="Send a test notification to Telegram and exit",
    )
    parser.add_argument(
        "--commit-only",
        action="store_true",
        help="Only sync and commit, skip bundle creation (for hourly runs)",
    )
    return parser.parse_args()


def load_config(backup_repo):
    """Load and validate backup-config.json from the backup repo."""
    config_path = os.path.join(backup_repo, "backup-config.json")
    if not os.path.isfile(config_path):
        log.error(f"Config not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    entries = config.get("entries", [])
    if not entries:
        log.warning("No entries in backup-config.json")
        return config, []

    validated = []
    for i, entry in enumerate(entries):
        if "path" not in entry:
            log.warning(f"Entry {i} missing 'path', skipping")
            continue
        entry["path"] = os.path.expanduser(entry["path"])
        validated.append(entry)

    return config, validated


def dest_path(src_path, backup_repo):
    """Compute the destination path in the backup repo for a source path.

    All paths map to __root__/ as a full mirror of /:
      ~/foo  -> <backup_repo>/__root__/Users/<user>/foo
      /foo   -> <backup_repo>/__root__/foo
    """
    return os.path.join(backup_repo, "__root__", src_path.lstrip("/"))


def _run(cmd, **kwargs):
    """Run a subprocess command, log it and its output, return the result."""
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
    else:
        cmd_str = cmd
    log.debug(f"  $ {cmd_str}")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.stdout and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            log.debug(f"    stdout: {line}")
    if result.stderr and result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log.debug(f"    stderr: {line}")
    return result


def _parse_refs(output):
    """Parse 'sha ref' lines into a set of tuples."""
    refs = set()
    for line in output.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            refs.add((parts[0], parts[1]))
    return refs


def _sync_git_repo(entry, backup_repo, dry_run):
    """Sync a git repo entry by creating a bundle. Returns True on failure."""
    src = entry["path"]
    dst = dest_path(src, backup_repo) + ".bundle"

    if not os.path.isdir(src):
        log.warning(f"  Git repo not found: {src}")
        return True

    if not os.path.isdir(os.path.join(src, ".git")):
        log.warning(f"  Not a git repo: {src}")
        return True

    # Compare refs to skip if unchanged
    result = _run(["git", "-C", src, "show-ref", "--head"])
    repo_refs = _parse_refs(result.stdout) if result.returncode == 0 else None

    if os.path.isfile(dst):
        result = _run(["git", "bundle", "list-heads", dst])
        bundle_refs = _parse_refs(result.stdout) if result.returncode == 0 else None
    else:
        bundle_refs = None

    if repo_refs is not None and bundle_refs is not None and repo_refs == bundle_refs:
        log.info(f"  Unchanged: {src}")
        return False

    if dry_run:
        log.info(f"  [dry-run] Would bundle git repo: {src} -> {dst}")
        return False

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    log.info(f"  Bundling {src} -> {dst}")
    result = _run(["git", "-C", src, "bundle", "create", dst, "--all"])
    if result.returncode != 0:
        log.warning(f"  Bundle failed for {src}: {result.stderr.rstrip()}")
        return True

    result = _run(["git", "-C", src, "bundle", "verify", dst])
    if result.returncode != 0:
        log.warning(f"  Bundle verify failed for {src}: {result.stderr.rstrip()}")
        os.remove(dst)
        return True
    log.info(f"  Verified OK: {src}")

    return False


def sync_entries(entries, backup_repo, dry_run):
    """Sync each entry into the backup repo. Returns set of failed paths."""
    failed = set()
    for entry in entries:
        if entry.get("type") == "git-repo":
            if _sync_git_repo(entry, backup_repo, dry_run):
                failed.add(entry["path"])
            continue

        src = entry["path"]
        dst = dest_path(src, backup_repo)
        is_dir = os.path.isdir(src)

        if not os.path.exists(src):
            log.warning(f"Source not found: {src}")
            failed.add(src)
            continue

        if is_dir:
            # Directory sync: rsync -a --delete src/ dst/
            cmd = ["rsync", "-a", "--delete"]
            for pattern in entry.get("ignore", []):
                cmd += ["--exclude", pattern]
            cmd += [src.rstrip("/") + "/", dst.rstrip("/") + "/"]
        else:
            # Single file: rsync src dst (ensure parent exists)
            cmd = ["rsync", src, dst]

        if dry_run:
            log.info(f"  [dry-run] {' '.join(cmd)}")
            continue

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_dir:
            os.makedirs(dst, exist_ok=True)

        log.info(f"  Syncing {src} -> {dst}")
        result = _run(cmd)
        if result.returncode != 0:
            log.warning(f"rsync failed for {src}: {result.stderr.rstrip()}")
            failed.add(src)
    return failed


SPECIAL_NAMES = {".git", "backup-config.json", "README.md", ".gitignore", "__log__",
                 "__root__", "net.xzer.work-backup-hourly.plist",
                 "net.xzer.work-backup-bundle.plist"}


def cleanup_removed_entries(entries, backup_repo, dry_run):
    """Remove files/dirs under __root__/ that don't belong to any config entry."""
    root_dir = os.path.join(backup_repo, "__root__")
    if not os.path.isdir(root_dir):
        return []

    # Build set of expected dest paths (absolute)
    expected = set()
    for entry in entries:
        dst = dest_path(entry["path"], backup_repo)
        if entry.get("type") == "git-repo":
            dst += ".bundle"
        expected.add(dst)

    removed = []
    _cleanup_dir(root_dir, expected, dry_run, removed)
    return removed


def _is_ancestor(path, expected):
    """Check if path is a parent/ancestor directory of any expected entry."""
    prefix = path.rstrip("/") + "/"
    return any(e.startswith(prefix) for e in expected)


def _is_covered(path, expected):
    """Check if path is covered by any expected entry (exact, ancestor, or descendant)."""
    if path in expected:
        return True
    if _is_ancestor(path, expected):
        return True
    # Check if path is inside an expected directory entry
    for e in expected:
        if path.startswith(e.rstrip("/") + "/"):
            return True
    return False


def _cleanup_dir(dir_path, expected, dry_run, removed):
    """Recursively clean children of a directory that aren't covered by entries."""
    for name in os.listdir(dir_path):
        full = os.path.join(dir_path, name)
        if _is_covered(full, expected):
            # Only recurse into ancestor dirs (they contain expected entries deeper down).
            # Don't recurse into expected dirs themselves — rsync manages their contents.
            if os.path.isdir(full) and not os.path.islink(full) and _is_ancestor(full, expected):
                _cleanup_dir(full, expected, dry_run, removed)
            continue
        if dry_run:
            log.info(f"  [dry-run] Would remove: {full}")
        else:
            log.info(f"  Removing: {full}")
            if os.path.islink(full):
                os.remove(full)
            elif os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
        removed.append(full)


def git_auto_commit(backup_repo, dry_run):
    """Stage all changes and commit if there are any. Returns True if a commit was made."""
    if dry_run:
        result = _run(["git", "-C", backup_repo, "status", "--short"])
        if result.stdout.strip():
            log.info("  [dry-run] Would commit changes:")
            for line in result.stdout.strip().splitlines():
                log.info(f"    {line}")
        else:
            log.info("  [dry-run] No changes to commit")
        return False

    # Stage everything
    result = _run(["git", "-C", backup_repo, "add", "-A"])
    if result.returncode != 0:
        log.error(f"git add failed: {result.stderr.rstrip()}")
        sys.exit(1)

    # Check if there are staged changes
    result = subprocess.run(
        ["git", "-C", backup_repo, "diff", "--cached", "--quiet"],
    )
    if result.returncode == 0:
        log.info("  No changes to commit")
        return False

    # Commit
    msg = f"backup: sync {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    result = _run(["git", "-C", backup_repo, "commit", "-m", msg])
    if result.returncode != 0:
        log.error(f"git commit failed: {result.stderr.rstrip()}")
        sys.exit(1)

    log.info(f"  Committed: {msg}")
    return True


def create_bundle(backup_repo, bundle_dir, dry_run):
    """Create a git bundle, verify it, and copy to bundle_dir if configured."""
    filename = f"work-backup-{datetime.now().strftime('%Y-%m-%d')}.bundle"
    bundle_path = os.path.join(backup_repo, filename)

    if dry_run:
        log.info(f"  [dry-run] Would create bundle: {bundle_path}")
        if bundle_dir:
            log.info(f"  [dry-run] Would copy to: {os.path.join(bundle_dir, filename)}")
        return

    # Create bundle
    log.info(f"  Creating bundle: {bundle_path}")
    result = _run(["git", "-C", backup_repo, "bundle", "create", bundle_path, "--all"])
    if result.returncode != 0:
        log.error(f"Bundle creation failed: {result.stderr.rstrip()}")
        sys.exit(1)

    # Verify bundle
    log.info("  Verifying bundle...")
    result = _run(["git", "-C", backup_repo, "bundle", "verify", bundle_path])
    if result.returncode != 0:
        log.error(f"Bundle verification failed: {result.stderr.rstrip()}")
        log.error("Keeping previous bundle. Investigate the error.")
        os.remove(bundle_path)
        sys.exit(1)
    log.info("  Bundle verified OK")

    # Copy to bundle dir if configured
    if bundle_dir:
        os.makedirs(bundle_dir, exist_ok=True)
        dest = os.path.join(bundle_dir, filename)
        shutil.copy2(bundle_path, dest)
        log.info(f"  Copied to: {dest}")

    # Clean up bundle from repo dir (it's not meant to be committed)
    os.remove(bundle_path)


BUNDLE_RE = re.compile(r"^work-backup-(\d{4}-\d{2}-\d{2})\.(bundle|skipped)$")
MAX_CONSECUTIVE_SKIPPED = 10


def should_force_bundle(bundle_dir):
    """Return True if last MAX_CONSECUTIVE_SKIPPED entries are all .skipped."""
    if not bundle_dir or not os.path.isdir(bundle_dir):
        return False
    entries = sorted(globmod.glob(os.path.join(bundle_dir, "work-backup-*.*")))
    # Filter to only matching entries
    entries = [e for e in entries if BUNDLE_RE.match(os.path.basename(e))]
    recent = entries[-MAX_CONSECUTIVE_SKIPPED:]
    if len(recent) < MAX_CONSECUTIVE_SKIPPED:
        return False
    return all(e.endswith(".skipped") for e in recent)


def create_skipped_marker(bundle_dir, dry_run):
    """Create a 0-byte .skipped placeholder in bundle_dir."""
    filename = f"work-backup-{datetime.now().strftime('%Y-%m-%d')}.skipped"
    if dry_run:
        log.info(f"  [dry-run] Would create skipped marker: {filename}")
        return
    os.makedirs(bundle_dir, exist_ok=True)
    path = os.path.join(bundle_dir, filename)
    open(path, "w").close()
    log.info(f"  Created skipped marker: {filename}")


def has_unbundled_commits(backup_repo, bundle_dir):
    """Check if backup repo HEAD differs from the last bundle's commit."""
    result = _run(["git", "-C", backup_repo, "rev-parse", "HEAD"])
    if result.returncode != 0:
        return True
    head = result.stdout.strip()

    if not bundle_dir or not os.path.isdir(bundle_dir):
        return True

    bundles = sorted(globmod.glob(os.path.join(bundle_dir, "work-backup-*.bundle")))
    if not bundles:
        return True

    last_bundle = bundles[-1]
    result = _run(["git", "bundle", "list-heads", last_bundle])
    if result.returncode != 0:
        return True

    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "HEAD":
            return head != parts[0]

    return True


def retention_cleanup(bundle_dir, dry_run):
    """Apply GFS retention policy to bundles in bundle_dir."""
    today = date.today()
    bundles = []
    for path in sorted(globmod.glob(os.path.join(bundle_dir, "work-backup-*.*"))):
        m = BUNDLE_RE.match(os.path.basename(path))
        if not m:
            continue
        bundle_date = date.fromisoformat(m.group(1))
        bundles.append((path, bundle_date))

    if not bundles:
        log.info("  No bundles found")
        return

    keep = set()
    weekly_kept = {}   # (iso_year, iso_week) -> latest date
    monthly_kept = {}  # (year, month) -> latest date

    for path, d in bundles:
        age = (today - d).days
        if age <= 30:
            # Daily tier: keep all
            keep.add(path)
        elif age <= 89:
            # Weekly tier: keep last bundle per ISO week
            key = d.isocalendar()[:2]
            if key not in weekly_kept or d > weekly_kept[key][1]:
                weekly_kept[key] = (path, d)
        elif age <= 364:
            # Monthly tier: keep last bundle per month
            key = (d.year, d.month)
            if key not in monthly_kept or d > monthly_kept[key][1]:
                monthly_kept[key] = (path, d)
        # else: expired (365+), don't keep

    for path, _ in weekly_kept.values():
        keep.add(path)
    for path, _ in monthly_kept.values():
        keep.add(path)

    to_delete = [path for path, _ in bundles if path not in keep]
    if not to_delete:
        log.info(f"  All {len(bundles)} bundle(s) retained")
        return

    for path in to_delete:
        if dry_run:
            log.info(f"  [dry-run] Would delete: {os.path.basename(path)}")
        else:
            os.remove(path)
            log.info(f"  Deleted: {os.path.basename(path)}")

    log.info(f"  Kept {len(keep)}, deleted {len(to_delete)}")


def run_pre_sync_commands(entries, dry_run):
    """Run preSyncCommand for entries that define one. Returns set of failed paths."""
    failed = set()
    for entry in entries:
        cmd = entry.get("preSyncCommand")
        if not cmd:
            continue
        path = entry["path"]
        if dry_run:
            log.info(f"  [dry-run] Would run pre-sync: {cmd}")
            continue
        log.info(f"  Running pre-sync for {path}: {cmd}")
        try:
            result = _run(cmd, shell=True, timeout=60)
            if result.returncode != 0:
                log.warning(f"Pre-sync failed (exit {result.returncode}) for {path}")
                failed.add(path)
        except subprocess.TimeoutExpired:
            log.warning(f"Pre-sync timed out for {path}")
            failed.add(path)
    return failed


def main():
    args = parse_args()
    backup_repo = os.path.expanduser(args.backup_repo)
    backup_repo = os.path.abspath(backup_repo)
    dry_run = args.dry_run
    commit_only = args.commit_only

    if not os.path.isdir(backup_repo):
        print(f"ERROR: Backup repo not found: {backup_repo}", file=sys.stderr)
        sys.exit(1)

    setup_logging(backup_repo)

    if dry_run:
        log.info("=== DRY RUN MODE ===\n")

    log.info(f"Backup repo: {backup_repo}")

    config, entries = load_config(backup_repo)
    telegram_config = config.get("telegram", {})

    if args.notify_test:
        log.info("Sending test notification to Telegram...")
        notify_telegram(telegram_config,
                        f"✅ Backup notification test\nRepo: {backup_repo}")
        log.info("Done.")
        return

    bundle_dir = config.get("bundleDir")
    if bundle_dir:
        bundle_dir = os.path.expanduser(bundle_dir)
        bundle_dir = os.path.abspath(bundle_dir)
    notify_success = config.get("notifyOnSuccess", False)

    log.info(f"Entries: {len(entries)}")
    if bundle_dir:
        log.info(f"Bundle dir: {bundle_dir}")
    if commit_only:
        log.info("Mode: commit-only")
    log.info("")

    for entry in entries:
        log.info(f"  - {entry['path']}")

    try:
        # Pre-sync commands
        log.info("\n--- Pre-sync commands ---")
        failed_paths = run_pre_sync_commands(entries, dry_run)
        if failed_paths:
            log.info(f"  {len(failed_paths)} entry(ies) failed pre-sync, will be skipped")
        active_entries = [e for e in entries if e["path"] not in failed_paths]

        # Sync files
        log.info("\n--- Syncing files ---")
        sync_failed = sync_entries(active_entries, backup_repo, dry_run)
        if sync_failed:
            log.info(f"  {len(sync_failed)} entry(ies) failed to sync")

        # Cleanup removed entries
        log.info("\n--- Cleanup ---")
        removed = cleanup_removed_entries(entries, backup_repo, dry_run)
        if removed:
            log.info(f"  Removed {len(removed)} item(s)")
        else:
            log.info("  Nothing to clean up")

        # Git auto-commit
        log.info("\n--- Git commit ---")
        git_auto_commit(backup_repo, dry_run)

        # commit-only mode: stop here
        if commit_only:
            log.info("\nDone (commit-only).")
            return

        # Full mode: decide whether to create a bundle
        unbundled = has_unbundled_commits(backup_repo, bundle_dir)
        force = not unbundled and should_force_bundle(bundle_dir)

        if unbundled or force:
            if force:
                log.info(f"\nNo new commits since last bundle, but last {MAX_CONSECUTIVE_SKIPPED} entries are skipped — forcing bundle.")

            # Bundle creation + verification + copy
            log.info("\n--- Bundle ---")
            create_bundle(backup_repo, bundle_dir, dry_run)

            # Retention cleanup
            if bundle_dir:
                log.info("\n--- Retention cleanup ---")
                retention_cleanup(bundle_dir, dry_run)

            log.info("\nDone.")
            if notify_success and not dry_run:
                filename = f"work-backup-{datetime.now().strftime('%Y-%m-%d')}.bundle"
                notify_telegram(telegram_config,
                                f"✅ Bundle created: {filename}")
        else:
            log.info("\n--- No changes since last bundle ---")
            if bundle_dir:
                create_skipped_marker(bundle_dir, dry_run)
            log.info("\nDone.")
            if notify_success and not dry_run:
                notify_telegram(telegram_config,
                                "ℹ️ No changes since last bundle, skipped")

    except SystemExit as e:
        if e.code != 0:
            notify_telegram(telegram_config,
                            f"🚨 Backup failed (exit {e.code})\nRepo: {backup_repo}")
        raise
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        notify_telegram(telegram_config,
                        f"🚨 Backup failed: {e}\nRepo: {backup_repo}")
        sys.exit(1)


if __name__ == "__main__":
    main()
