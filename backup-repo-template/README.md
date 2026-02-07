# Work Backup

This repository mirrors files from the machine for backup purposes.

## Path Conventions

- **`__root__/` = `/` (filesystem root)**: All backup content lives here as a full mirror.
  - `~/.zshrc` → `__root__/Users/<user>/.zshrc`
  - `/etc/some-config` → `__root__/etc/some-config`

## Special Files

These are not mirrored files:
- `backup-config.json` — defines what to back up
- `net.xzer.work-backup.plist` — launchd schedule
- `README.md` — this file
