# Overview 1.26 validation

Implemented against the public modules currently installed on 3 November 2026, retaining the existing local bridge, console and Notion fixes. No credentials are included. No release was pushed.

- 232 selected regression tests: console, existing Codex UI and 35 new fleet checks. Run in an isolated copy with temporary account directories, as the unprivileged user. No test suite was run against live profiles.
- Browser: original 110 DOM IDs retained; account ordering; independent optimization; immediate manual selection enable/disable; composer routing to Claude/Codex; Shift+Enter, Esc; settings and five skins; profile filtering and application; quick model selection; full-screen input; widths 390/768/1024/1440/1920; no JS errors and no requests to the live API.
- Real GNU screen and PTY with a fake native executable: exact thread resume, model/effort pinning, model change, account switch with a shared history index and separate account home, readiness, Unicode input. No external model calls were made.
- Native CLI help checked for explicit resume ID, model, cwd, approval, sandbox and sqlite_home configuration. Current live choice is preserved; model names are not migrated.
- Cross-account eligibility, stale/error/unknown quota exclusions, deferred busy switching, failed-start/modal rollback, queued model/profile updates and input deduplication tested with fakes. There is currently only one real Codex account; a physical switch between two real authenticated accounts has not been exercised.

The old repository tests included assertions predating already deployed repairs. Updated those assertions for the separate systemd console, explicit long CLI flags and cwd, mouse termcap fix, current Full profiles, availability and emergency styling. The 0.6 second test timeout now uses a proportionate Enter retry. New behavior checks explicitly cover cancellation on missing thread history (no silent fallback) and the console composer. The pre-change baseline had 10 failures and 2 fixture errors; these were audited before updating assertions.

Deployment waits for the current bridge response and native turn to finish. It changes public runtime files only, checks baseline hashes, backs up replaced code, restarts cc-limits only, verifies the unchanged console PID/thread/model/effort/cwd and new API/UI, and rolls back code if health checks fail. Account credentials, work profile settings, cxw and native console services are not part of the deployment file set.
