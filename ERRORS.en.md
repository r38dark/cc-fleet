# 🚨 Error reference

[🇷🇺 Русский](ERRORS.md) · 🇬🇧 English

Error codes actually caught while running `cc-fleet` — on account cards in
the panel, in `journalctl -u cc-limits`, and inside the Claude Code session
itself.

Anthropic's official Messages API error list lives at
[docs.anthropic.com/en/api/errors](https://docs.anthropic.com/en/api/errors).
It gives general definitions (`invalid_request_error`, `authentication_error`,
`permission_error`, `rate_limit_error`, etc.) for the public API. This page
covers what that documentation doesn't: the specifics of the Claude Code
subscription OAuth flow, account rotation, and how these codes actually show
up in practice in this project.

---

## 429 — Too Many Requests

**Officially:** `rate_limit_error` — the organization hit a request rate
limit, a daily/weekly cap, or a workspace spend limit.

In the context of a Claude Code Pro/Max subscription, a 429 usually doesn't
mean "too many API calls" — it means the subscription window is full (the
5-hour session or the weekly quota). Same HTTP code under the hood, different
cause and different fix. It shows up here in **two entirely different
situations**:

### 429a — real: the subscription window is spent
**When it happens:** the account has genuinely burned through its 5-hour
session limit. The card shows `429` with `resets HH:MMam/pm` — the next
window reset time.

**What to do:** nothing — this is the normal signal for the balancer, it
will switch to a fresh account on its own (or pause work if none are left —
see `pause_ctl.py` in the README). If it doesn't switch, check that the
`cc-limits` service is actually running (`systemctl status cc-limits`) and
that `autoswitch`/`optimize` are enabled in `config.json`.

### 429b — spurious: the monitor itself is polling too often
**When it happens:** the `cc-limits` service itself calls Anthropic's
`usage`/`plan` endpoints too frequently — either for inactive accounts
(polled at the same rate as the active one), or for the active account with
`poll_sec` set too low. This has nothing to do with how much the account has
actually "worked" — it's a rate limit on the check requests themselves.

**What to do:** update to a current `cc-fleet` release — since v1.6.0
inactive accounts are cached (`inactive_poll_sec`, 300s by default) and
skipped on most ticks, and since v1.8.0/v1.9.1 a caught 429 sets a
`backoff_until` that the background poller itself respects, instead of
retrying immediately. If 429s still recur, raise `poll_sec` in
`config.json` (120s by default) and restart the service.

---

## 400 — Bad Request (`invalid_grant`)

**Officially:** `invalid_request_error` — but this particular flavor isn't
about request format, it's OAuth: `POST /v1/oauth/token` returned a body of
`{"error": "invalid_grant", "error_description": "Refresh token expired"}`.

**When it happens:** the account card just shows `400` — the actual cause
is in the response body, visible only in the log. It happens to an account
that hasn't been "live" for a while — no real human sign-in (browser/app
login, a payment renewal), only an automatic background token refresh. A
subscription refresh token, unlike an access token, has its own lifespan and
doesn't renew itself forever through a purely mechanical refresh.

**What to do:** sign in to that account manually — via the web (`claude.ai`)
or the mobile app, with a normal password/code login. Then re-log the
profile into `cc-fleet`: via the "Log in again" web button in the panel
(`/cc/`), or by hand — `/login` inside the `screen` session, then
`cc-switch save N`.

---

## 403 — Forbidden (WAF on the User-Agent)

**Officially:** `permission_error` — the key/token doesn't have permission
for the resource.

**When it happens:** while refreshing the OAuth token (`POST
https://platform.claude.com/v1/oauth/token`) with a plain library-default
User-Agent (`urllib`/`requests` with no explicit header) — Anthropic's
network-level WAF blocks the request as suspicious before it even reaches
the OAuth logic.

**What to do:** the token-refresh request needs a normal browser/client-like
User-Agent, not a bare library default — `cc-switch`/`cc-limits` already
handle this. If this code shows up from your own script calling
`oauth/token` directly, add a `User-Agent` header by hand.

---

## Text error (not an HTTP code): "organization has disabled Claude subscription access"

**When it happens:** this isn't an API response code — it's a message from
the CLI itself when it tries to use an account whose plan has actually
dropped from Pro/Max to Free (for example, a failed auto-renewal payment).
It can look like a 429 in monitoring logs if the plan check goes through the
same rate-limited endpoint.

**What to do:** check the billing status of that account (`claude.ai` →
Settings → Billing) and restore Pro/Max. Until the plan is restored,
`cc-fleet` shouldn't switch to that account anyway — the free-guard in
`cc-switch` blocks switching to a Free-plan account without an explicit
`--force`.

---

## License

[MIT](LICENSE)
