# Running SAPDemo on a MacBook

Operating a small public deployment from a laptop on a desk. Written for the
machine this was built and tested on:

> 2020 Intel MacBook Pro · macOS · 2.0 GHz quad-core i5 · 16 GB RAM ·
> Docker Desktop · Ethernet

Every host-level setting below is **documented, not automated**. Nothing in this
repository changes a macOS preference, and no script here needs administrator
rights.

---

## Intel versus Apple Silicon

This stack runs on both, and **no image pins a platform**. Every image used
(`postgres:17.7-bookworm`, `node:22-bookworm-slim`, `python:3.12-slim-bookworm`,
`cloudflare/cloudflared`) publishes `linux/amd64` and `linux/arm64`, so Docker
picks the host's architecture and the same compose file works on either.

Hardcoding `platform: linux/amd64` would force emulation on Apple Silicon —
slower, hotter, and for no benefit. There is a test asserting no `platform:` key
appears in the compose file.

What differs in practice on this Intel machine:

- **Builds are slow.** The API image is a full scientific Python stack; the
  first build takes tens of minutes. Subsequent builds reuse layers.
- **The fans will run** during a build and during first-run seeding. That is
  expected.
- **Rosetta is irrelevant.** Everything here is native `amd64`.

---

## 1. Docker Desktop

### Install

Download the **Intel chip** build from docker.com and install it. Confirm:

```bash
docker --version
docker compose version
uname -m            # x86_64
```

### Start after login

**Docker Desktop → Settings → General → Start Docker Desktop when you sign in.**

This matters more than it sounds. Every container uses `restart: unless-stopped`,
so the stack comes back on its own — but only once the Docker daemon is running,
and on macOS the daemon is Docker Desktop, which is a user application that
starts **after a login**. See "FileVault and unattended reboots" below.

### Resources

**Settings → Resources.** On a 16 GB machine:

| Setting | Value | Why |
| --- | --- | --- |
| CPUs | 3 | Leaves one core for macOS. 4 makes the whole machine unresponsive during a build. |
| Memory | 8 GB | Leaves 8 GB for macOS and Safari. Postgres + API + Streamlit + Next idle well under this. |
| Swap | 2 GB | Absorbs build spikes without thrashing. |
| Disk image size | 64 GB+ | Images, layers, build cache and the database volume. |

Apply & Restart afterwards.

If a build is killed with exit code 137, it ran out of memory — raise the limit
or close other applications and rebuild.

---

## 2. Power and sleep

The stack must stay up while the lid is closed on a desk.

**System Settings → Lock Screen / Displays / Battery:**

| Setting | Value |
| --- | --- |
| *Prevent automatic sleeping on power adapter when the display is off* | **On** |
| Turn display off on power adapter | 10 minutes (fine — the display sleeping is not the machine sleeping) |
| Put hard disks to sleep when possible | Off |
| Wake for network access | On |

Letting the **display** sleep is good: it saves power and heat and changes
nothing about the containers.

### Keep the lid open

A MacBook with the lid closed and no external display **sleeps**, regardless of
the settings above. There is no supported way around that; the "clamshell" mode
people describe needs an external display, keyboard and mouse attached.

So: **leave the lid open.** Angle the screen back and let the display sleep. If
the machine must be closed, attach an external display.

You can confirm what is holding sleep off:

```bash
pmset -g assertions
```

`caffeinate -s` is a per-session workaround, not a substitute for the setting —
it stops the moment the terminal closes.

---

## 3. Heat and ventilation

A 2020 Intel i5 under sustained load gets hot and throttles.

- Hard, flat surface. Not a bed, sofa, cushion or laptop bag.
- Nothing covering the rear vent or the underside.
- A stand that lifts the back helps noticeably.
- Somewhere with air. Not a closed cabinet or a drawer.

```bash
sudo powermetrics --samplers smc -n 1 | grep -i "CPU die temperature"
```

Idle for this stack is a few percent CPU. Sustained high temperature with no
build running means something is wrong — check `docker stats` for a container
spinning.

---

## 4. Network

**Use Ethernet.** A USB-C or Thunderbolt adapter is a few pounds and removes the
most common cause of an unexplained outage.

- The tunnel is an **outbound** connection. No port forwarding, no inbound
  firewall rule, no static IP, no dynamic DNS.
- Give the Mac a **DHCP reservation** on the router anyway — useful for finding
  it, harmless otherwise.
- **Wi-Fi works** but reconnects on channel changes and roams between bands, and
  each reconnection is a brief outage.
- If Ethernet is connected, set service order so it is preferred:
  **System Settings → Network → ⋯ → Set Service Order**.

Your router and modem are single points of failure for the whole deployment.
Nothing in this stack changes that.

---

## 5. FileVault and unattended reboots

FileVault is full-disk encryption and you should leave it **on** — the machine
holds a database credential and a tunnel token.

The consequence is the important part:

> **A FileVault-encrypted Mac cannot log in by itself after a restart.**
> It boots to a password prompt. Until somebody types the password, no user is
> logged in, Docker Desktop has not started, and the deployment is down.

So an unattended power cut means **the site stays down until a person is
physically at the machine**. That is the trade, and it is the right one for a
laptop holding credentials.

After any restart:

1. Log in at the keyboard.
2. Wait for Docker Desktop (the whale icon stops animating).
3. Containers restart automatically — `restart: unless-stopped`.
4. `./scripts/status_selfhosted.sh` to confirm.

If you disable FileVault to allow automatic login, understand you have traded
disk encryption for uptime on a machine holding a tunnel token. Do not do this
without deciding it deliberately.

### Test the recovery

Do this **once, deliberately, before publishing** — not automatically, and not
during a demonstration:

```bash
./scripts/backup_selfhosted.sh --verify     # first
sudo shutdown -r now
# log in, wait for Docker Desktop, then:
./scripts/status_selfhosted.sh
./scripts/verify_selfhosted.sh
```

A recovery procedure nobody has run is a hypothesis. Time it, so you know what
"back up shortly" actually means.

---

## 6. Disk

```bash
df -h /                       # host disk
docker system df              # what Docker is using
./scripts/status_selfhosted.sh
```

Docker on macOS grows a disk image and does not shrink it on its own. Reclaim:

```bash
docker image prune -a         # images no container uses
docker builder prune          # build cache - the big one after several builds
docker system prune           # both, plus stopped containers and unused networks
```

**Never `docker system prune --volumes`.** That deletes `sapdemo-postgres`,
which is the database. There is no flag in any script in this repository that
removes a volume, for exactly this reason.

Container logs are bounded at 10 MB × 5 files each by the compose file, so they
cannot silently fill the disk.

Check disk monthly, or after any period of frequent rebuilding.

---

## 7. macOS updates

A macOS update restarts the machine. With FileVault on, that means the
deployment is down until somebody logs in.

- **Turn off automatic installation of macOS updates.**
  *System Settings → General → Software Update → ⓘ*: leave security responses
  on, turn "Install macOS updates" off.
- Update deliberately, in a window you choose, when you can be at the machine.
- Take a backup first.
- Docker Desktop occasionally needs reinstalling after a major macOS upgrade.

### A maintenance window

Pick one — say the first Sunday of the month, early:

```bash
./scripts/backup_selfhosted.sh --verify
./scripts/stop_selfhosted.sh
# macOS updates, Docker Desktop update, reboot
# log in, wait for Docker Desktop
./scripts/start_selfhosted.sh
./scripts/verify_selfhosted.sh
```

---

## 8. Backups to an external encrypted drive

The database holds fictional demonstration data, so the stakes are low — but a
restore you have never tested is not a backup, and testing it costs nothing.

1. Attach an external drive.
2. **Disk Utility → Erase → APFS (Encrypted)**, set a password, store it in your
   password manager.
3. Point backups at it:

```bash
# .env.selfhosted
BACKUP_DIR=/Volumes/SAPDemoBackup
BACKUP_RETENTION=14
```

```bash
./scripts/backup_selfhosted.sh --verify
```

`--verify` restores the dump into a throwaway database, checks it actually
contains tables and rows, and drops it. The backup script does **not** encrypt —
the encryption is the drive's. That is stated in the script itself so nobody
assumes otherwise.

Eject the drive properly when detaching it.

---

## 9. Scheduling with launchd

macOS has no working `cron` for this; use `launchd`. A nightly reset of the
demonstration data, at 04:00:

`~/Library/LaunchAgents/com.sapdemo.reset.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sapdemo.reset</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd /Users/YOU/Projects/SAPDemo &amp;&amp; ./scripts/reset_public_demo.sh --yes</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/sapdemo-reset.log</string>
  <key>StandardErrorPath</key><string>/tmp/sapdemo-reset.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.sapdemo.reset.plist
```

A `LaunchAgent` runs only while a user is logged in — which, given FileVault, is
the same condition the deployment itself needs. Use the same shape with
`backup_selfhosted.sh` for a nightly backup at 03:00.

The reset script refuses to run unless `DEMO_MODE=true`, so a scheduled job
cannot quietly wipe a database that has stopped being a demonstration.

---

## 10. Daily and weekly

**Whenever you think of it**

```bash
./scripts/status_selfhosted.sh
```

**Weekly**

```bash
./scripts/verify_selfhosted.sh
./scripts/backup_selfhosted.sh --verify
df -h / && docker system df
```

**Monthly**

- Maintenance window (section 7)
- `docker builder prune`
- Confirm backups exist on the external drive and one of them restores
- Re-test `https://demo.[DOMAIN]` from cellular data

---

## What this repository will not do to your Mac

No script here changes a macOS setting, installs software, modifies power
management, touches the firewall, changes network configuration, or needs
`sudo`. Every host-level step on this page is yours to perform deliberately.
