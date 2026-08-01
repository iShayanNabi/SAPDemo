# Backup and recovery

What is backed up, how to restore it, and how to find out whether a backup
actually works **before** you need it.

---

## What is state, and what is not

| Where | What | Backed up |
| --- | --- | --- |
| `sapdemo-postgres` volume | The demonstration database | **Yes** |
| `sapdemo-api-data` volume | Exports and runtime files | No — regenerated |
| `data/sample/` | The bundled fictional datasets | No — committed to git |
| `.env.selfhosted` | Credentials | **Your job.** Password manager, not this. |
| Images | Built from the repository | No — rebuild |

The database holds analyses computed from committed fictional data. Losing it
costs a `reset_public_demo.sh` run, not a catastrophe. Backups exist so that a
restore is *practised* rather than improvised, and so a bad migration is
recoverable.

`.env.selfhosted` is deliberately not in any backup this repository takes.
Copying a file containing a tunnel token onto a drive that then travels is a
worse risk than losing it — it is two values, and both are reissuable.

---

## Taking a backup

```bash
./scripts/backup_selfhosted.sh                     # to $BACKUP_DIR
./scripts/backup_selfhosted.sh --dir /Volumes/Enc  # to an external drive
./scripts/backup_selfhosted.sh --verify            # + prove it restores
```

What it does:

- `pg_dump -Fc` — PostgreSQL's custom format. Compressed, and restorable
  selectively by `pg_restore`. A plain SQL dump is readable but cannot be
  restored table by table, which is exactly what you want on the bad day.
- Refuses to start if there is less than 256 MB free. Failing before the dump
  beats failing half way through one.
- **Checks the result is really a dump.** A file whose first bytes are not
  `PGDMP` is discarded, as is anything under 1 KB. `pg_dump` writing an error to
  stdout produces a file, and a file looks like success in a directory listing.
- Writes a **SHA-256 checksum** beside it. A backup you have not checksummed is
  a backup you have not verified.
- Applies retention: keeps the newest `BACKUP_RETENTION` (default 14) and
  deletes older ones **matching its own name pattern only**. This is the only
  thing in the project that ever deletes a backup.

### It does not encrypt

Stated plainly in the script itself. Point `--dir` at an encrypted volume — a
FileVault-protected external disk — if the contents matter. The demonstration
database holds only fictional data, so the local default is proportionate; a
database holding anything else is not this script's job.

---

## Restoring

### Verify without touching anything

```bash
./scripts/restore_selfhosted.sh --file backups/sapdemo-....dump --into-throwaway
```

Creates a temporary database, restores into it, counts what arrived, drops it.
Nothing live is touched. This is what `--verify` calls, and it is the mode you
should use routinely.

It **fails** if the restored database has fewer than five tables. A dump that
restores into an empty schema is a dump of nothing, and reporting "restore
succeeded" about it would be the exact false assurance this script exists to
prevent.

### Restore over the live database

```bash
./scripts/restore_selfhosted.sh --latest
./scripts/restore_selfhosted.sh --file backups/sapdemo-....dump
```

Destructive, and it behaves accordingly:

1. Validates the dump header.
2. **Verifies the checksum**, and refuses outright if it fails. A half-restored
   database is worse than a stopped one, because it looks like it worked.
3. Requires you to type `restore` in full. No `-y` shortcut by accident.
4. **Takes a safety copy of the current database first**, to
   `backups/pre-restore-<timestamp>.dump`. Restoring the wrong backup is a
   normal mistake; it is only unrecoverable if the thing it overwrote is gone.
5. Stops the API and UI so nothing holds a connection.
6. Drops, recreates, restores.
7. Starts the services and waits for health.

---

## Testing recovery

**A backup that has never been restored is a hypothesis.**

Monthly, or after any schema change:

```bash
./scripts/backup_selfhosted.sh --verify
```

Once, deliberately, before publishing — a full disposable restore:

```bash
./scripts/backup_selfhosted.sh                       # 1. take one
./scripts/reset_public_demo.sh --yes                 # 2. change the state
./scripts/restore_selfhosted.sh --latest             # 3. put it back
./scripts/verify_selfhosted.sh                       # 4. confirm
```

Time it, so "we can restore" becomes "we can restore in about four minutes".

---

## External encrypted drive

1. **Disk Utility → Erase → APFS (Encrypted)**. Store the password in a password
   manager, not on the machine.
2. Point backups at it:

```bash
# .env.selfhosted
BACKUP_DIR=/Volumes/SAPDemoBackup
BACKUP_RETENTION=14
```

3. Schedule it — see the `launchd` example in
   [`MACBOOK_SELF_HOSTING.md`](MACBOOK_SELF_HOSTING.md).
4. If the drive is not mounted, the backup script fails loudly rather than
   silently writing to a directory that only exists while the drive is absent.
5. Eject properly before detaching.

---

## Retention

Default 14 backups. Nightly, that is two weeks.

The script deletes only files matching `sapdemo-*.dump` in the backup directory,
along with their checksums. A glob matching more would eventually delete
somebody else's file that happened to be in the same folder.

`pre-restore-*.dump` safety copies are **not** covered by retention and are never
deleted automatically. Clear them out by hand when you are confident.

---

## Losing the whole machine

The database is the only thing that is not reproducible from the repository, and
it holds fictional data seeded from files that *are* in the repository. So:

```bash
git clone https://github.com/iShayanNabi/SAPDemo.git
cd SAPDemo
cp .env.selfhosted.example .env.selfhosted   # fill it in
./scripts/start_selfhosted.sh --build        # seeds itself on first run
```

Restore a backup on top only if you want the specific records that existed
before. Most of the time you do not — `DEMO_SEED_ON_EMPTY` produces an equivalent
demonstration from the committed data.

The two things you genuinely cannot recreate from the repository are the
Cloudflare tunnel token and the database password. Both are reissuable in
minutes: create a new tunnel, generate a new password.

---

## What no script here will ever do

- Delete a volume. No flag in this project removes `sapdemo-postgres`; that is
  `docker volume rm`, typed deliberately.
- Delete a backup it did not create.
- Delete source files, migrations, configuration or secrets.
- Restore without verifying the checksum first.
- Report a restore as successful without checking something actually arrived.
