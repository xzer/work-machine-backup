# Comprehensive Work Machine Backup Solution

## Overview
A git-based backup solution that collects critical work machine data into a versioned repository, automatically synced to cloud storage via Google Drive.

## Architecture
```
Local (outside Google Drive)
└── work-machine-backup/         (Git Repository - Working Copy)
    ├── configs/                 (Configuration files)
    ├── scripts/                 (Custom scripts & tools)
    ├── metadata/                (System & project metadata)
    ├── docs/                    (Documentation & notes)
    ├── collect-backup.sh        (Collect files into repo)
    └── create-bundle.sh         (Create & sync git bundle)

Google Drive Synced Folder
└── backups/
    ├── work-machine-backup-2026-02-04.bundle
    ├── work-machine-backup-2026-02-03.bundle
    └── work-machine-backup-2026-02-02.bundle

Cloud (Google Drive)
└── Automatic sync of bundle files
```

## Components to Backup

### 1. Config Files
- Shell configurations (.bashrc, .zshrc, .bash_profile)
- Git config (.gitconfig, .gitignore_global)
- SSH config (config only, keys separately)
- IDE settings (VSCode, IntelliJ, etc.)
- Terminal configs (iTerm2, etc.)
- Claude Code configs (~/.claude/)
- Other dotfiles

### 2. Scripts and Tools
- Custom automation scripts
- Utility scripts
- Project-specific tools
- Aliases and functions

### 3. Project Metadata
- List of installed packages (brew, npm, pip, etc.)
- List of active git repositories
- Database of work projects/directories
- Tool versions and dependencies

### 4. Documentation
- Work notes and references
- Project documentation
- Knowledge base entries
- Setup instructions

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

### Regular Backup Process
1. Run collection script to gather latest files into repo
2. Review changes (git diff)
3. Commit with descriptive message
4. Run bundle script to create dated .bundle file (YYYY-MM-DD format)
5. **Verify bundle integrity**: `git bundle verify <bundle-file>`
6. If verification passes, copy bundle to Google Drive synced folder
7. Run retention cleanup script to maintain backup policy
8. Google Drive automatically syncs bundle to cloud (atomic, safe)

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
- Create repo structure
- Set up .gitignore for sensitive files
- Create README with backup manifest

### Phase 2: Collection Scripts
- Script to copy config files
- Script to export package lists
- Script to catalog git repositories
- Script to organize documentation

### Phase 3: Automation
- Main backup.sh orchestrator
- Dry-run mode for testing
- Logging and error handling
- Change detection

### Phase 4: Maintenance
- Periodic review of what's backed up
- Update scripts as environment changes
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
