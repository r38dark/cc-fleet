# ⚡ cc-fleet

[🇷🇺 Русский](README.md) · 🇬🇧 English

**Self-host dashboard for rotating multiple Claude Code accounts across usage limits.**

Monitors the usage limits (5-hour / weekly) of several Pro/Max accounts on a
single VDS at once, automatically switches the active session once a
threshold is hit, and shows a live read-only mirror of the running Claude
Code console — all in one web panel, no third-party services or clouds.

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
2. copy `cc_limits.py` → `/opt/cc-limits`, `cc-switch` →
   `/usr/local/bin/cc-switch`,
3. create N empty profile slots in `/root/.claude-profiles/accN`,
4. generate `config.json` with a random `hook_token`,
5. install and start the systemd service,
6. verify the service actually responds (health-check),
7. *(optional)* set up the nginx vhost + Basic Auth.

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

## Management

| Command / URL | What it does |
|---|---|
| `cc-switch list` | which profiles exist, which one is active |
| `cc-switch <N>` / `cc-switch next` | manually switch the active session |
| `/cc/` (or `curl 127.0.0.1:8877/api/limits?token=<hook_token>`) | limits, auto-switch, console mirror |
| `/opt/cc-limits/config.json` | `autoswitch`, `threshold`, `optimize`, `poll_sec`, `switch_cooldown_sec`, `chat_id`, `screen_session`, `port` |

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

## License

[MIT](LICENSE)
