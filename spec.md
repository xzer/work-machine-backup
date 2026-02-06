# Comprehensive Work Machine Backup Solution

## Overview
A git-based backup solution that collects critical work machine data into a versioned repository, automatically synced to cloud storage via Google Drive.

## Architecture

Two separate repositories serve different purposes:

```
Project Repo (this repo - development)
└── work-machine-backup/
    ├── scripts/                 (Backup automation scripts)
    ├── docs/                    (Documentation & notes)
    ├── spec.md                  (This specification)
    └── CLAUDE.md

Backup Repo (separate - data, managed by scripts from project repo)
└── <backup-repo>/               (Repo root = home directory mirror)
    ├── backup-config.json       (Defines what to back up)
    ├── README.md                (Path conventions)
    ├── __root__/                (Mirror for files outside ~)
    ├── .zshrc                   (~/.zshrc)
    ├── .gitconfig               (~/.gitconfig)
    └── ...

Google Drive Synced Folder
└── backups/
    ├── <backup-repo>-2026-02-04.bundle
    ├── <backup-repo>-2026-02-03.bundle
    └── <backup-repo>-2026-02-02.bundle

Cloud (Google Drive)
└── Automatic sync of bundle files
```

### Repo Separation
- **Project repo**: Scripts, spec, docs — normal development workflow
- **Backup repo**: Backup content only — automated commits from sync scripts
- Scripts in the project repo take the backup repo path as a parameter, read `backup-config.json` from the backup repo, and sync files into it

## Backup Content Organization

### Mirrored Path Structure
The backup repo root is home-mapped (i.e. repo root = `~`). Files are mirrored directly at the repo root preserving their path relative to home. For files outside the home directory, use `__root__/` which maps to `/`. This approach:
- Self-documents where each file came from
- Eliminates name collisions naturally
- Makes restoration straightforward (paths map directly back)
- Keeps paths short for the common case (most files are under `~`)

Example:
```
<backup-repo>/
├── backup-config.json           (config, not a mirrored file)
├── README.md                    (conventions, not a mirrored file)
├── .zshrc                       (~/.zshrc)
├── .gitconfig                   (~/.gitconfig)
├── .config/
│   └── git/
│       └── ignore               (~/.config/git/ignore)
└── __root__/
    └── etc/
        └── some-config          (/etc/some-config)
```

### Sync Requirement
The mirrored files in the backup repo must be a 100% mirror of the source. If a file is removed from source or from `backup-config.json`, it should be removed from the backup repo as well. Implementation strategy TBD.

### Backup Config (`backup-config.json`)
A JSON config file in the backup repo root defines what to back up. Each entry specifies:

- **path** (required): Source file or directory path to copy
- **preSyncCommand** (optional): Command to run before copying, to dump/refresh the file
- **description** (optional): What this entry is and why it's backed up
- **ignore** (optional): Patterns to exclude when backing up directories

Example:
```json
{
  "entries": [
    {
      "path": "~/.zshrc",
      "description": "Zsh configuration"
    },
    {
      "path": "~/.config/vscode/extensions.json",
      "preSyncCommand": "code --list-extensions > ~/.config/vscode/extensions.json",
      "description": "VSCode extensions list"
    },
    {
      "path": "~/.config/iterm2",
      "description": "iTerm2 configuration",
      "ignore": ["cache/*", "logs/*"]
    }
  ]
}
```

### Typical Backup Targets
- Shell configurations (.bashrc, .zshrc, .bash_profile)
- Git config (.gitconfig, .gitignore_global)
- SSH config (config only, not keys)
- IDE settings (VSCode, IntelliJ, etc.)
- Terminal configs (iTerm2, etc.)
- Claude Code configs (~/.claude/)
- Custom scripts and tools
- Other dotfiles

## Sensitive Data Handling
**Important:**
- SSH private keys should be backed up separately (encrypted or secure vault)
- Credentials and tokens should use encryption or be excluded
- Use .gitignore to prevent accidental commits of secrets

## Backup Workflow

### Initial Setup
1. Create local git repo (outside Google Drive)
2. Set up directory structure
3. Create collection scripts
4. Initialize with current state
5. Create initial bundle and copy to Google Drive folder
6. Verify Google Drive syncs the bundle

### Regular Backup Process (Python + rsync)

Technology choice: **Python** for the main script logic, **rsync** for file sync operations.
- Python handles config parsing, pre-sync commands, git operations, bundling, and error handling
- rsync handles efficient file mirroring with deletion and exclude pattern support

Pipeline:
1. Read `backup-config.json` from the backup repo
2. Run `preSyncCommand` for entries that define one
3. Use rsync to sync each entry into the backup repo (mirrored paths, with `--delete` for removals)
4. Auto-commit changes to the backup repo git
5. Create git bundle (dated .bundle file, YYYY-MM-DD format)
6. **Verify bundle integrity**: `git bundle verify <bundle-file>`
7. If verification passes, copy bundle to Google Drive synced folder
8. Run retention cleanup to maintain backup policy
9. Google Drive automatically syncs bundle to cloud (atomic, safe)

**Note**: If bundle verification fails, the script should:
- Alert the user
- Keep the previous valid bundle
- Not proceed with cleanup
- Log the error for investigation

### Retention Policy (Grandfather-Father-Son Strategy)
- **Daily**: Keep all bundles from last 30 days
- **Weekly**: Keep one bundle per week for 30-90 days ago (retain first bundle of each week)
- **Monthly**: Keep one bundle per month for 90-365 days ago (retain first bundle of each month)
- **Cleanup**: Delete bundles older than 1 year

This provides:
- 30 daily restore points for recent changes
- ~8-12 weekly restore points for medium-term recovery
- ~9-12 monthly restore points for long-term archival
- Estimated total: ~50-55 bundle files maximum

### Git Bundle Benefits
- **Atomic Sync**: Single file = no partial corruption risk
- **Git Native**: Can clone/pull directly from bundle
- **Versioned**: Keep multiple dated snapshots
- **Verifiable**: Git validates bundle integrity
- **Safe**: Interrupted sync just means old bundle remains

### Automation Options
- Manual: Run script when needed
- Scheduled: Use cron/launchd for periodic backups
- Triggered: Hook into system events or workflows

## Implementation Plan

### Phase 1: Repository Setup
- Create backup repo structure
- Set up .gitignore for sensitive files
- Create initial `backup-config.json`

### Phase 2: Backup Script (Python)
- Read `backup-config.json` and validate entries
- Execute pre-sync commands
- rsync each entry to mirrored path in backup repo
- Auto-commit changes to backup repo
- Create and verify git bundle
- Copy bundle to Google Drive sync folder

### Phase 3: Retention & Cleanup
- Implement retention policy cleanup script
- Logging and error handling

### Phase 4: Automation & Maintenance
- Scheduled runs (cron/launchd)
- Dry-run mode for testing
- Periodic review of what's backed up
- Document restoration procedures

## Restoration Strategy
1. Get latest .bundle file from Google Drive
2. Clone from bundle: `git clone work-machine-backup-YYYY-MM-DD.bundle`
3. Verify bundle integrity: `git bundle verify <bundle-file>`
4. Run restoration scripts to copy configs back
5. Reinstall packages from manifests
6. Restore configs to proper locations
7. Manually handle sensitive credentials

## Benefits
- **Version Control**: Track changes over time with git history
- **Cloud Persistence**: Automatic sync to Google Drive
- **Selective Backup**: Only what matters
- **Human-Readable**: All configs in plain text
- **Portable**: Easy to restore on new machine

## Considerations
- Google Drive sync may have delays
- Git repo size should be manageable (avoid large binaries)
- Sensitive data needs special handling
- Regular testing of restoration process

## Next Steps
1. Determine exact Google Drive folder path
2. Decide on sensitive data strategy
3. Create initial repo structure
4. Build collection scripts
5. Test backup and restore workflow
