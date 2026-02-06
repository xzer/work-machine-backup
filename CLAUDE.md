# Work Machine Backup

A comprehensive backup solution for work machine configurations, scripts, and metadata using git bundles and Google Drive for cloud persistence.

## Project Description

This project provides an automated backup system that:
- Collects critical configuration files, custom scripts, and project metadata
- Maintains version history using git
- Creates atomic git bundle snapshots for safe cloud sync
- Implements a sophisticated retention policy (daily/weekly/monthly)
- Syncs bundles to Google Drive for cloud backup

## Key Features

- **Git Bundle Based**: Atomic, corruption-resistant backups
- **Smart Retention**: Daily (30d), Weekly (3mo), Monthly (1yr) retention policy
- **Version Control**: Full git history in each bundle
- **Cloud Safe**: Single-file bundles prevent sync corruption
- **Automated**: Scripts for collection, bundling, and cleanup

## Documentation

For detailed specifications, architecture, and implementation plan, see [spec.md](./spec.md).

## Quick Start

(To be implemented)

1. Configure paths in scripts
2. Run initial backup
3. Set up automation (optional)

## Project Structure

This is the **project repo** for development (scripts, spec, docs). The actual backup content lives in a separate **backup repo**.

```
work-machine-backup/ (this repo)
├── CLAUDE.md           (This file)
├── spec.md            (Detailed specification)
├── scripts/           (Backup automation scripts)
├── docs/              (Documentation and notes)
```

The backup repo (separate, path passed as parameter to scripts):
```
<backup-repo>/
├── backup-config.json (Defines what to back up)
├── backup/            (Mirrored path structure of backup contents)
```
