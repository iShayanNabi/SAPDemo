# Self-hosted troubleshooting

Symptoms, causes and fixes for the SAPDemo self-hosted stack. Start here:

```bash
./scripts/status_selfhosted.sh      # what is running, and what is configured
./scripts/verify_selfhosted.sh      # what is actually correct
./scripts/logs_selfhosted.sh api    # why
```

---

## Docker Desktop does not start

**Symptom:** every script fails with *"Docker is installed but not running."*

The daemon on macOS **is** Docker Desktop, a user application. It cannot run
before somebody logs in.

1. Open Docker Desktop from Applications and wait for the whale to stop
   animating.
2. Confirm **Settings → General → Start Docker Desktop when you sign in** is on.
3. If it hangs on "Starting…":
   ```bash
   killall Docker && open -a Docker
   ```
4. If it still hangs: **Settings → Troubleshoot → Clean / Purge data** destroys
   volumes — **that includes the database.** Take a backup first, or accept
   reseeding.
5. After a major macOS upgrade, reinstalling Docker Desktop is sometimes the
   fastest fix.

**After any restart of the Mac,** remember FileVault: the machine sits at a
password prompt, nobody is logged in, and Docker has not started. The
deployment is down until a person types the password. See
[`MACBOOK_SELF_HOSTING.md`](MACBOOK_SELF_HOSTING.md).

---

## A container is unhealthy or restarting

```bash
./scripts/status_selfhosted.sh
./scripts/logs_selfhosted.sh <service>
```

### `cloudflared` is restarting

**Almost always: no tunnel token.** It cannot authenticate, exits, and
`restart: unless-stopped` starts it again.

This is the **expected** state before the tunnel exists. `status_selfhosted.sh`
and `verify_selfhosted.sh` both report it as expected rather than as a fault
when `CLOUDFLARE_TUNNEL_TOKEN` is empty.

If a token *is* set and it still restarts: the token is wrong or the tunnel was
deleted. Create a new tunnel and take a new token — see
[`CLOUDFLARE_TUNNEL_SETUP.md`](CLOUDFLARE_TUNNEL_SETUP.md).

### `api` never becomes healthy

The first start on a fresh volume runs migrations and then seeds ten modules.
On a quad-core i5 that takes minutes; `start_period` is 240 s for exactly this
reason.

```bash
./scripts/logs_selfhosted.sh api
```

- *"Waiting for the database to accept connections"* — the database is still
  starting. Wait.
- An Alembic error — the migration failed. The API deliberately does not start
  against a half-built schema. Read the error; a mismatched
  `alembic_version` is fixed by `./scripts/reset_public_demo.sh`.
- *"WARNING: seeding did not complete"* — the API is up but the demonstration
  may be partly empty. See the next section.

### `database` never becomes healthy

```bash
./scripts/logs_selfhosted.sh database
```

- *"database files are incompatible with server"* — the volume was created by a
  different major PostgreSQL version. Dump with the old version, or recreate the
  volume and reseed.
- *"could not create shared memory segment"* — Docker Desktop memory is too low.
  Raise it to 8 GB.
- Permission errors on a fresh volume — the compose file grants the database
  `CHOWN`, `SETUID`, `SETGID` and friends for exactly this. If they were removed
  from `cap_add`, put them back.

---

## Seeding failed, or a module has no data

```bash
./scripts/logs_selfhosted.sh api | grep -i "could not be seeded"
./scripts/reset_public_demo.sh --yes
```

**A specific failure worth recognising:**

```
DataError: (psycopg.errors.StringDataRightTruncation)
value too long for type character varying(20)
```

A column is narrower than a value the code writes. This is invisible on SQLite,
which does not enforce `VARCHAR` length, and the whole test suite runs on
SQLite — so a green run does not rule it out.

It has happened once, to `ai_prompt_version`, and two of the ten modules failed
to seed while everything else looked fine. Fixed by migration `b8e6a24f1d35`,
and `tests/integration/test_column_widths.py` now compares declared widths
against the constants the code writes. If you see this for a different column,
that test file is where the fix belongs.

---

## Cannot open the site on the Mac

The deployed configuration publishes **nothing** — that is the design, not a
fault. `curl http://127.0.0.1:3000` returning nothing is correct.

Use the debug overlay:

```bash
./scripts/start_selfhosted.sh --debug
curl -I http://127.0.0.1:3000     # website
curl -I http://127.0.0.1:8501     # demonstration
curl -I http://127.0.0.1:8000/docs
```

Two things that surprised us and will surprise you:

- **The API port needs the overlay's `networks:` block.** Docker cannot publish
  a port from a container attached only to a network declared `internal: true`.
  It accepts the `ports:` entry, reports the container healthy, and never
  creates the mapping. The overlay adds `edge` to the API for this reason.
- **The website's Launch Demo button is compiled in at build time.** A website
  image built for the deployment links to the real demo hostname, so on
  `127.0.0.1:3000` that button goes nowhere. The debug overlay overrides the
  build arguments — but you must **rebuild** after switching:

  ```bash
  docker compose -f docker-compose.selfhosted.yml -f docker-compose.debug.yml \
    --env-file .env.selfhosted build website
  ```

If a port is in use:

```bash
lsof -nP -iTCP:3000 -sTCP:LISTEN
# then change DEBUG_WEBSITE_PORT in .env.selfhosted
```

---

## The public site does not load

Work outwards.

```bash
./scripts/status_selfhosted.sh                 # 1. is the stack up?
./scripts/logs_selfhosted.sh cloudflared       # 2. is the tunnel connected?
dig +short [DOMAIN]                            # 3. does DNS resolve?
curl -I https://[DOMAIN]                       # 4. from another network
```

- **Nothing resolves** — DNS has not propagated, or the nameserver change was
  not made. See [`GODADDY_NAMESERVER_SETUP.md`](GODADDY_NAMESERVER_SETUP.md).
- **Cloudflare error 1033** — the tunnel has no connector. `cloudflared` is down
  or has no valid token.
- **Error 502** — the tunnel is connected but the target is not. Check the
  public hostname points at `website:3000` (service name, not localhost) and
  that the service is healthy.
- **Works on your wifi, not on cellular** — a stale local DNS cache made it look
  fine. Cellular is the honest test.

```bash
sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
```

---

## The demonstration asks for a login and never lets me in

That is Cloudflare Access.

- The address must be on the allow list **exactly**. Not a different alias, not
  a different domain.
- The one-time PIN goes to that address; check spam.
- Confirm the policy uses **Emails**, not "Emails ending in", and that a
  **Block / Everyone** rule sits below rather than above the allow rule.
- Access logs (**Zero Trust → Logs → Access**) show who was allowed and refused.

---

## Uploads are being accepted on the public demonstration

This is the one to fix immediately.

```bash
./scripts/status_selfhosted.sh | grep -i upload
./scripts/verify_selfhosted.sh
```

`DEMO_MODE` is not `true`, or `DEMO_ALLOW_UPLOADS` is `true`. Fix
`.env.selfhosted` and:

```bash
./scripts/restart_selfhosted.sh
```

If demo mode is on and uploads still succeed, stop the stack and investigate
before restarting it. The guard is in `app/core/demo.py` and is called from
`read_upload_within_limit` and both validators.

---

## Data disappeared after a restart

Check first:

```bash
grep DEMO_RESET_ON_START .env.selfhosted     # must be false
docker volume inspect sapdemo-postgres        # must exist
```

- `DEMO_RESET_ON_START=true` wipes the database on **every** start. That is why
  it defaults to false.
- `docker compose down -v` removes volumes. No script here passes `-v`;
  `stop_selfhosted.sh` deliberately has no flag that does.
- Docker Desktop **Troubleshoot → Clean / Purge data** removes volumes.

Restore: `./scripts/restore_selfhosted.sh --latest`, or just
`./scripts/reset_public_demo.sh --yes` — the data is fictional and reseeds.

---

## The Mac is slow, hot, or the fans are loud

```bash
docker stats --no-stream
top -o cpu -n 10 -l 1
```

- **During a build:** expected. The API image is a full scientific Python stack.
- **At idle:** something is looping. A restarting container (usually
  `cloudflared` without a token) burns CPU steadily.
- Docker Desktop CPUs set to 4 of 4 makes the whole machine unresponsive. Use 3.
- Check ventilation — see [`MACBOOK_SELF_HOSTING.md`](MACBOOK_SELF_HOSTING.md).

---

## Disk is filling up

```bash
df -h /
docker system df
docker builder prune          # usually the biggest win
docker image prune -a
```

**Never `docker system prune --volumes`** — that deletes the database.

Container logs are capped at 10 MB × 5 files each by the compose file, so they
are not the cause.

---

## Starting completely over

Keeping the data:

```bash
./scripts/stop_selfhosted.sh
./scripts/start_selfhosted.sh --build
```

Discarding it deliberately:

```bash
./scripts/backup_selfhosted.sh --verify    # first
./scripts/stop_selfhosted.sh
docker volume rm sapdemo-postgres          # typed by hand, on purpose
./scripts/start_selfhosted.sh --build      # reseeds on first run
./scripts/verify_selfhosted.sh
```

---

## When to stop and think

Stop the stack — `./scripts/stop_selfhosted.sh` — rather than experimenting, if:

- uploads are being accepted on a public hostname
- the API or the database turns out to be reachable from outside
- a secret has appeared somewhere it should not be
- an Access policy turns out to be broader than intended

Then work through
[`DEMO_SECURITY_CHECKLIST.md`](DEMO_SECURITY_CHECKLIST.md) from the top before
starting again.
