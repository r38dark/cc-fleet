# Mirrored profile preview

This is an isolated design prototype. It never imports or starts the live server,
reads account credentials, executes a command, or connects a native console/agent.
All accounts, quotas, authentication and profile actions are sample data. The
in-memory state resets when the preview process restarts.

From a checkout, run:

```sh
python3 preview/preview_runtime.py 8878
python3 -m unittest discover -s preview -p test_profile_scenarios.py -v
```

Open `http://127.0.0.1:8878/`. The page expects its mock API under
`/cc-demo-api/`; the test server accepts that prefix directly. `?pause=1` shows a
sample paused state. Bind is restricted to loopback. Put authentication in front
of a public preview; this sample server is not a production service.

Each engine exposes the same five scenarios: leads the opposite engine, solo,
solo Full, reserve with the agent, and temporary emergency. The common state
machine enforces one leader, explicit confirmation for added authority, previous
scenario restoration, a two-hour emergency deadline, and revision conflicts.
Automatic reserve is symmetric and uses test availability only. Manual stop
suppresses automatic reactivation until the other engine recovers. The test-only
`POST /test/availability` supplies `{engine, available}` without querying accounts.

The UI activates mirrored controls only when `GET /api/profiles` advertises both
engines; otherwise the existing Codex picker and handlers remain. Live console
adapters, persistence/recovery, real limit availability, OS access enforcement and
busy-turn coordination are deliberately not implemented by this prototype.
Approval of this design is separate from implementing and deploying those paths.
