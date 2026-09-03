# ⚡ cc-fleet

[🇷🇺 Русский](README.md) · 🇬🇧 English

**Self-host dashboard for rotating multiple Claude Code accounts across usage limits.**

Monitors the usage limits (5-hour / weekly) of several Pro/Max accounts on a
single VDS at once, automatically switches the active session once a
threshold is hit, and shows a live read-only mirror of the running Claude
Code console — all in one web panel, no third-party services or clouds.

And when there is nothing left to switch to, it pauses the work and lifts the
pause on its own as soon as the nearest window resets.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Shell: bash](https://img.shields.io/badge/installer-bash-89e051.svg)](install.sh)
[![Python: 3](https://img.shields.io/badge/backend-python%203-3776ab.svg)](cc_limits.py)

---

## Screenshots

Accounts panel — cards showing 5-hour and weekly session usage percentage,
active account highlighted:

![cc-fleet dashboard](screenshots/dashboard.png)

Live console mirror — a read-only copy of what's happening in the Claude
Code `screen` session right now, no SSH needed:

![Console mirror](screenshots/console.png)

Limit-state banner (v1.2.0) — shows up at the top of the panel only when
there's something to say; in normal operation it isn't rendered at all
(screenshots below are in Russian, the panel itself is RU/EN):

![Paused on limits](screenshots/banner-pause.png)
![Nothing to switch to](screenshots/banner-hard.png)
![Active account is full](screenshots/banner-gate.png)

## Features

- 📊 **Multi-account limit monitoring** at once — 5-hour window and weekly
  quota, with a countdown to reset.
- 🔁 **Auto-switch** the active account at a configurable session-usage
  threshold (checkbox in the panel, threshold as a slider/field).
- 🎯 **Limit optimization mode** — the service itself decides which account
  to use right now, to stretch the combined limit across all accounts;
  manual switch buttons are blocked while it runs.
- 🖥 **Live console mirror** — the same `screen` session visible in your
  terminal, streamed to the browser in real time (read-only).
- 🚦 **Gate for background jobs** (`limits_gate.py`) — one line in your own
  script keeps cron runs and watchers from starting while the active account
  has already burned its window: otherwise they eat exactly the limit you
  need for yourself.
- ⏸ **Limit pause with an alarm** (`pause_ctl.py`) — when every account is
  above the threshold and there is nothing to switch to, work goes on pause,
  and a system cron lifts it at the nearest window reset and wakes the live
  session. Nothing lives inside the Claude Code session itself, so the pause
  survives a restart, `/clear` and a reboot.
- 🔔 **State banner** at the top of the panel (RU/EN): "limits reached —
  nothing to switch to", "active account is full — background jobs paused",
  "paused, resuming at 16:03" with a countdown. In normal operation there is
  no banner.
- 🔐 No OAuth tokens ever leave your machine — everything lives on your own
  server, under your own root.
- 🧩 One install script, no web wizards or dependencies on someone else's
  infrastructure.

## Requirements

- Your own VDS/server (root access), Ubuntu/Debian with `apt`.
- Claude Code installed (`npm i -g @anthropic-ai/claude-code`), the `claude`
  command must be in `PATH` (`install.sh` will warn if it isn't).
- 2+ Pro/Max Claude accounts to rotate between.
- *(optional)* a domain with an A-record pointing at the server — for the
  web panel over HTTPS instead of bare `127.0.0.1:8877`.

## Installation

```bash
git clone https://github.com/r38dark/cc-fleet.git
cd cc-fleet
sudo ./install.sh
```

The installer will ask: the name of the `screen` session Claude Code runs
in, how many accounts to set up, the auto-switch threshold, whether you want
an nginx domain with Basic Auth, and whether you want Telegram
notifications. Then it will, on its own:

1. install `python3-pyte python3-pexpect screen` (+ `nginx apache2-utils` if
   you chose a web domain),
2. copy `cc_limits.py`, `limits_gate.py`, `pause_ctl.py` → `/opt/cc-limits`,
   `cc-switch` → `/usr/local/bin/cc-switch`,
3. create N empty profile slots in `/root/.claude-profiles/accN`,
4. generate `config.json` with a random `hook_token` (on a repeat run it
   updates the existing one, keeping your token and your keys),
5. install and start the systemd service,
6. install the pause alarm cron job (`/etc/cron.d/cc-limits-pause`, ticking
   once a minute),
7. verify the service actually responds (health-check on `/api/limits` and
   `/api/pause`),
8. *(optional)* set up the nginx vhost + Basic Auth.

Non-interactive, for scripts/CI:

```bash
CC_FLEET_YES=1 sudo -E ./install.sh
```

All parameters are taken from `CC_FLEET_*` environment variables (see the
top of `install.sh`) or their defaults.

HTTPS is set up separately after installation, by hand: if you installed
nginx — `certbot --nginx -d <domain>`.

## Running Claude Code itself inside the screen session

The service only monitors/switches — you start the session itself the
standard way:

```bash
screen -S claude -dm claude
```

(the session name must match the one given to install.sh — `claude` by
default). A live session picks up the token swap on the fly, no restart
needed.

## Onboarding accounts

Either of two ways works — both save the account into
`/root/.claude-profiles/accN/`:

**Via the web "Log in again" button** (`/cc/` panel, if you installed
nginx) — install.sh already created N empty slots
(`oauth_account.json: {}`); the button starts `claude auth login` in an
isolated temp HOME, hands you an OAuth link, you sign in in the browser
under the account you want and paste the code back into the page.

**Manually, if the panel isn't up yet:**

```bash
# inside the screen session from the step above — claude is already open there
/login    # sign in under the account you want, inside the TUI
```

then in a regular shell:

```bash
cc-switch save 1   # saves the CURRENT live session as profile acc1
```

Repeat `/login` + `cc-switch save N` for each next account. To check what
the service sees: `cc-switch list`.

## Background-job gate and limit pause (v1.2.0)

Rotation answers "which account should I work on". Two cases are left open:
background (headless) jobs quietly eating the active account's window, and
the moment when **every** account is above the threshold.

**The gate.** `limits_gate.py` is a short script that talks through its exit
code: `10` — do not start now, `0` — go ahead. Put it at the top of your own
cron script:

```bash
python3 /opt/cc-limits/limits_gate.py || exit 0   # rc=10 — just don't start
```

It blocks in two cases: the active account is above the threshold (wait for
the balancer to move to a fresh one), or every account is above it (nothing
to switch to). If `snapshot.json` is missing or stale, the gate **lets the
job through** (fail-open): an extra run beats a silently dead daemon.

**The pause.** `pause_ctl.py` keeps its state in `pause_state.json` next to
the snapshot, and a system cron job (`/etc/cron.d/cc-limits-pause`, ticking
once a minute) wakes it — which is why the pause survives a session restart,
`/clear` and a reboot.

```bash
python3 /opt/cc-limits/pause_ctl.py set --reason "all accounts above threshold" \
        --note "what's left unfinished — I'll see it on wake-up"
python3 /opt/cc-limits/pause_ctl.py status      # current state + gate verdict
python3 /opt/cc-limits/pause_ctl.py clear       # lift it by hand
```

The resume time comes from the nearest 5-hour window reset across all
accounts (+3 minutes — a window doesn't free up instantly). On every tick the
cron job re-checks the gate: still red — it silently moves the alarm to the
new window and bumps the re-check counter; green — it lifts the pause and
"types" a wake-up line into the Claude Code `screen` session (`screen -X
stuff`) so the work continues on its own. The message is overridable via the
`pause_wake_message` key in `config.json`; it is **strictly ASCII** — a
`screen` started without `-U` takes non-ASCII as byte garbage and throws it
straight into the session's input.

All of this is visible in the panel: `GET /api/pause` returns the very state
`pause_ctl` computes — the banner, the gate and the alarm read the same
files, so the page can't promise one thing while background jobs do another.

## Management

| Command / URL | What it does |
|---|---|
| `cc-switch list` | which profiles exist, which one is active |
| `cc-switch <N>` / `cc-switch next` | manually switch the active session |
| `/cc/` (or `curl 127.0.0.1:8877/api/limits?token=<hook_token>`) | limits, auto-switch, console mirror |
| `curl 127.0.0.1:8877/api/pause?token=<hook_token>` | banner state: level (`none`/`gate`/`hard`), pause, nearest reset |
| `python3 /opt/cc-limits/limits_gate.py` | may a background job start right now (rc `0`/`10`) |
| `python3 /opt/cc-limits/pause_ctl.py set\|status\|clear` | limit pause with an automatic wake-up |
| `/opt/cc-limits/config.json` | `autoswitch`, `threshold`, `optimize`, `poll_sec`, `switch_cooldown_sec`, `chat_id`, `screen_session`, `port`, `pause_wake_message` |

## Upgrading from a previous version

```bash
cd cc-fleet && git pull
sudo ./install.sh          # you can keep the same answers
```

A repeat run is idempotent: the `hook_token` and the keys already in
`config.json` are preserved, account profiles are left alone. What gets
updated is the files in `/opt/cc-limits`, the systemd unit, the cron alarm
and the nginx config (if you chose nginx). If you'd rather not run the
installer again — copy `cc_limits.py`, `limits_gate.py`, `pause_ctl.py` into
`/opt/cc-limits`, add the cron line from `install.sh`, and restart the
service.

## Telegram notifications (optional)

The service reads the bot token from
`/root/.claude/channels/telegram/.env` (`TELEGRAM_BOT_TOKEN=...`) — this is
the file used by Claude Code's official Telegram channel. If the channel
isn't set up yet — set it up (`claude channels` in the Claude Code docs) or
write the line into that file by hand. The recipient's `chat_id` goes into
`config.json`. Without a `chat_id`, notifications are just silently skipped
— the service runs as usual.

## Without nginx / without a domain

The service listens only on `127.0.0.1:<port>`. Put your own reverse proxy
in front:

- The main page (`GET /`) is only served if the proxy sent an `X-Auth-User`
  header (usually from Basic Auth) — this way the panel never faces the
  internet unauthenticated.
- Every API route (`/api/...`) can be called without that header too — with
  `?token=<hook_token>` in the query string. The panel itself talks to the
  API this way (browsers don't always forward Basic Auth into `fetch()`),
  so you'll typically want TWO proxy locations: one with Basic Auth →
  service root (`X-Auth-User` from the proxy), and one without Auth →
  `/api/` (access gated only by knowing `hook_token`). See the nginx block
  that `install.sh` generates for an example.

## What's NOT included in this package

- A personal agents/supervisor dashboard — a separate layer on top of
  Claude Code, unrelated to account rotation, not part of this repo.
- An "escalation" feature (background cost-escalation monitoring) — cut
  out, specific to a different system.
- HTTPS/certbot — a manual step after `install.sh`.

## Version history

- **v1.2.0** — limit gate for background jobs (`limits_gate.py`), a pause
  with an alarm that outlives the session (`pause_ctl.py` + cron), the state
  banner in the panel and `GET /api/pause`, idempotent re-runs of
  `install.sh`.
- **v1.1.0** — RU/EN panel UI, fixed the web "Log in again" button.
- **v1.0.0** — first release: limit monitoring, auto-switching, console
  mirror, `cc-switch`, installer.

## License

[MIT](LICENSE)
