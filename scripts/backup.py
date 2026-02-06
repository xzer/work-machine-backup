#!/usr/bin/env python3
"""Backup script: syncs files per backup-config.json, commits, bundles."""

import argparse
from datetime import date, datetime, timedelta
import glob as globmod
import re
import json
import os
import shutil
import subprocess
import sys


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
    return parser.parse_args()


def load_config(backup_repo):
    """Load and validate backup-config.json from the backup repo."""
    config_path = os.path.join(backup_repo, "backup-config.json")
    if not os.path.isfile(config_path):
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    entries = config.get("entries", [])
    if not entries:
        print("WARNING: No entries in backup-config.json")
        return config, []

    validated = []
    for i, entry in enumerate(entries):
        if "path" not in entry:
            print(f"WARNING: Entry {i} missing 'path', skipping", file=sys.stderr)
            continue
        entry["path"] = os.path.expanduser(entry["path"])
        validated.append(entry)

    return config, validated


def dest_path(src_path, backup_repo):
    """Compute the destination path in the backup repo for a source path.

    Mirroring rules:
      ~/foo  -> <backup_repo>/foo
      /foo   -> <backup_repo>/__root__/foo
    """
    home = os.path.expanduser("~")
    if src_path.startswith(home + "/") or src_path == home:
        rel = os.path.relpath(src_path, home)
        return os.path.join(backup_repo, rel)
    else:
        # Absolute path outside home -> __root__
        return os.path.join(backup_repo, "__root__", src_path.lstrip("/"))


def rsync_entries(entries, backup_repo, dry_run):
    """Rsync each entry into the backup repo. Returns set of failed paths."""
    failed = set()
    for entry in entries:
        src = entry["path"]
        dst = dest_path(src, backup_repo)
        is_dir = os.path.isdir(src)

        if not os.path.exists(src):
            print(f"  WARNING: Source not found: {src}", file=sys.stderr)
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
            print(f"  [dry-run] {' '.join(cmd)}")
            continue

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_dir:
            os.makedirs(dst, exist_ok=True)

        print(f"  Syncing {src} -> {dst}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(
                f"  WARNING: rsync failed for {src}: {result.stderr.rstrip()}",
                file=sys.stderr,
            )
            failed.add(src)
    return failed


SPECIAL_NAMES = {".git", "backup-config.json", "README.md", ".gitignore"}


def cleanup_removed_entries(entries, backup_repo, dry_run):
    """Remove files/dirs in backup repo that don't belong to any config entry."""
    # Build set of expected dest paths (absolute)
    expected = set()
    for entry in entries:
        dst = dest_path(entry["path"], backup_repo)
        expected.add(dst)

    removed = []
    # Walk top-level items in backup repo
    for name in os.listdir(backup_repo):
        if name in SPECIAL_NAMES:
            continue
        full = os.path.join(backup_repo, name)
        if _is_covered(full, expected):
            # If it's a directory that is expected, still check children
            if os.path.isdir(full):
                _cleanup_dir(full, expected, dry_run, removed)
            continue
        # Not covered by any entry — remove
        if dry_run:
            print(f"  [dry-run] Would remove: {full}")
        else:
            print(f"  Removing: {full}")
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
        removed.append(full)

    return removed


def _is_covered(path, expected):
    """Check if path is an expected entry or is an ancestor of one."""
    if path in expected:
        return True
    # Check if path is a parent directory of any expected path
    prefix = path.rstrip("/") + "/"
    return any(e.startswith(prefix) for e in expected)


def _cleanup_dir(dir_path, expected, dry_run, removed):
    """Recursively clean children of a directory that aren't covered by entries."""
    for name in os.listdir(dir_path):
        full = os.path.join(dir_path, name)
        if _is_covered(full, expected):
            if os.path.isdir(full):
                _cleanup_dir(full, expected, dry_run, removed)
            continue
        if dry_run:
            print(f"  [dry-run] Would remove: {full}")
        else:
            print(f"  Removing: {full}")
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
        removed.append(full)


def git_auto_commit(backup_repo, dry_run):
    """Stage all changes and commit if there are any. Returns True if a commit was made."""
    if dry_run:
        result = subprocess.run(
            ["git", "-C", backup_repo, "status", "--short"],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            print("  [dry-run] Would commit changes:")
            for line in result.stdout.strip().splitlines():
                print(f"    {line}")
        else:
            print("  [dry-run] No changes to commit")
        return False

    # Stage everything
    result = subprocess.run(
        ["git", "-C", backup_repo, "add", "-A"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git add failed: {result.stderr.rstrip()}", file=sys.stderr)
        sys.exit(1)

    # Check if there are staged changes
    result = subprocess.run(
        ["git", "-C", backup_repo, "diff", "--cached", "--quiet"],
    )
    if result.returncode == 0:
        print("  No changes to commit")
        return False

    # Commit
    msg = f"backup: sync {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    result = subprocess.run(
        ["git", "-C", backup_repo, "commit", "-m", msg],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: git commit failed: {result.stderr.rstrip()}", file=sys.stderr)
        sys.exit(1)

    print(f"  Committed: {msg}")
    return True


def create_bundle(backup_repo, bundle_dir, dry_run):
    """Create a git bundle, verify it, and copy to bundle_dir if configured."""
    filename = f"work-backup-{datetime.now().strftime('%Y-%m-%d')}.bundle"
    bundle_path = os.path.join(backup_repo, filename)

    if dry_run:
        print(f"  [dry-run] Would create bundle: {bundle_path}")
        if bundle_dir:
            print(f"  [dry-run] Would copy to: {os.path.join(bundle_dir, filename)}")
        return

    # Create bundle
    print(f"  Creating bundle: {bundle_path}")
    result = subprocess.run(
        ["git", "-C", backup_repo, "bundle", "create", bundle_path, "--all"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Bundle creation failed: {result.stderr.rstrip()}", file=sys.stderr)
        sys.exit(1)

    # Verify bundle
    print("  Verifying bundle...")
    result = subprocess.run(
        ["git", "bundle", "verify", bundle_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Bundle verification failed: {result.stderr.rstrip()}", file=sys.stderr)
        print("  Keeping previous bundle. Investigate the error.", file=sys.stderr)
        os.remove(bundle_path)
        sys.exit(1)
    print("  Bundle verified OK")

    # Copy to bundle dir if configured
    if bundle_dir:
        os.makedirs(bundle_dir, exist_ok=True)
        dest = os.path.join(bundle_dir, filename)
        shutil.copy2(bundle_path, dest)
        print(f"  Copied to: {dest}")

    # Clean up bundle from repo dir (it's not meant to be committed)
    os.remove(bundle_path)


BUNDLE_RE = re.compile(r"^work-backup-(\d{4}-\d{2}-\d{2})\.bundle$")


def retention_cleanup(bundle_dir, dry_run):
    """Apply GFS retention policy to bundles in bundle_dir."""
    today = date.today()
    bundles = []
    for path in sorted(globmod.glob(os.path.join(bundle_dir, "work-backup-*.bundle"))):
        m = BUNDLE_RE.match(os.path.basename(path))
        if not m:
            continue
        bundle_date = date.fromisoformat(m.group(1))
        bundles.append((path, bundle_date))

    if not bundles:
        print("  No bundles found")
        return

    keep = set()
    weekly_kept = {}   # (iso_year, iso_week) -> earliest date
    monthly_kept = {}  # (year, month) -> earliest date

    for path, d in bundles:
        age = (today - d).days
        if age <= 30:
            # Daily tier: keep all
            keep.add(path)
        elif age <= 89:
            # Weekly tier: keep first bundle per ISO week
            key = d.isocalendar()[:2]
            if key not in weekly_kept or d < weekly_kept[key][1]:
                weekly_kept[key] = (path, d)
        elif age <= 364:
            # Monthly tier: keep first bundle per month
            key = (d.year, d.month)
            if key not in monthly_kept or d < monthly_kept[key][1]:
                monthly_kept[key] = (path, d)
        # else: expired (365+), don't keep

    for path, _ in weekly_kept.values():
        keep.add(path)
    for path, _ in monthly_kept.values():
        keep.add(path)

    to_delete = [path for path, _ in bundles if path not in keep]
    if not to_delete:
        print(f"  All {len(bundles)} bundle(s) retained")
        return

    for path in to_delete:
        if dry_run:
            print(f"  [dry-run] Would delete: {os.path.basename(path)}")
        else:
            os.remove(path)
            print(f"  Deleted: {os.path.basename(path)}")

    print(f"  Kept {len(keep)}, deleted {len(to_delete)}")


def run_pre_sync_commands(entries, dry_run):
    """Run preSyncCommand for entries that define one. Returns set of failed paths."""
    failed = set()
    for entry in entries:
        cmd = entry.get("preSyncCommand")
        if not cmd:
            continue
        path = entry["path"]
        if dry_run:
            print(f"  [dry-run] Would run pre-sync: {cmd}")
            continue
        print(f"  Running pre-sync for {path}: {cmd}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            if result.stdout:
                print(f"    stdout: {result.stdout.rstrip()}")
            if result.returncode != 0:
                print(
                    f"  WARNING: Pre-sync failed (exit {result.returncode}) for {path}",
                    file=sys.stderr,
                )
                if result.stderr:
                    print(f"    stderr: {result.stderr.rstrip()}", file=sys.stderr)
                failed.add(path)
        except subprocess.TimeoutExpired:
            print(f"  WARNING: Pre-sync timed out for {path}", file=sys.stderr)
            failed.add(path)
    return failed


def main():
    args = parse_args()
    backup_repo = os.path.expanduser(args.backup_repo)
    backup_repo = os.path.abspath(backup_repo)
    dry_run = args.dry_run

    if not os.path.isdir(backup_repo):
        print(f"ERROR: Backup repo not found: {backup_repo}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print("=== DRY RUN MODE ===\n")

    print(f"Backup repo: {backup_repo}")

    config, entries = load_config(backup_repo)
    bundle_dir = config.get("bundleDir")
    if bundle_dir:
        bundle_dir = os.path.expanduser(bundle_dir)
        bundle_dir = os.path.abspath(bundle_dir)

    print(f"Entries: {len(entries)}")
    if bundle_dir:
        print(f"Bundle dir: {bundle_dir}")
    print()

    for entry in entries:
        print(f"  - {entry['path']}")

    # Step 2: Pre-sync commands
    print("\n--- Pre-sync commands ---")
    failed_paths = run_pre_sync_commands(entries, dry_run)
    if failed_paths:
        print(f"  {len(failed_paths)} entry(ies) failed pre-sync, will be skipped")
    active_entries = [e for e in entries if e["path"] not in failed_paths]

    # Step 3: rsync file sync
    print("\n--- Syncing files ---")
    sync_failed = rsync_entries(active_entries, backup_repo, dry_run)
    if sync_failed:
        print(f"  {len(sync_failed)} entry(ies) failed to sync")

    # Step 4: Cleanup removed entries
    print("\n--- Cleanup ---")
    removed = cleanup_removed_entries(entries, backup_repo, dry_run)
    if removed:
        print(f"  Removed {len(removed)} item(s)")
    else:
        print("  Nothing to clean up")

    # Step 5: Git auto-commit
    print("\n--- Git commit ---")
    committed = git_auto_commit(backup_repo, dry_run)

    # Step 6: Bundle creation + verification + copy
    print("\n--- Bundle ---")
    create_bundle(backup_repo, bundle_dir, dry_run)

    # Step 7: Retention cleanup
    if bundle_dir:
        print("\n--- Retention cleanup ---")
        retention_cleanup(bundle_dir, dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
