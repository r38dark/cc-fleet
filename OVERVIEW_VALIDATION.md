# Overview 1.26 validation

Implemented against the public modules currently installed on 3 November 2026, retaining the existing local bridge, console and Notion fixes. No credentials are included. No release was pushed.

- 232 selected regression tests: console, existing Codex UI and 35 new fleet checks. Run in an isolated copy with temporary account directories, as the unprivileged user. No test suite was run against live profiles.
- Browser: original 110 DOM IDs retained; account ordering; independent optimization; immediate manual selection enable/disable; composer routing to Claude/Codex; Shift+Enter, Esc; settings and five skins; profile filtering and application; quick model selection; full-screen input; widths 390/768/1024/1440/1920; no JS errors and no requests to the live API.
- Real GNU screen and PTY with a fake native executable: exact thread resume, model/effort pinning, model change, account switch with a shared history index and separate account home, readiness, Unicode input. No external model calls were made.
- Native CLI help checked for explicit resume ID, model, cwd, approval, sandbox and sqlite_home configuration. Current live choice is preserved; model names are not migrated.
- Cross-account eligibility, stale/error/unknown quota exclusions, deferred busy switching, failed-start/modal rollback, queued model/profile updates and input deduplication tested with fakes. There is currently only one real Codex account; a physical switch between two real authenticated accounts has not been exercised.

The old repository tests included assertions predating already deployed repairs. Updated those assertions for the separate systemd console, explicit long CLI flags and cwd, mouse termcap fix, current Full profiles, availability and emergency styling. The 0.6 second test timeout now uses a proportionate Enter retry. New behavior checks explicitly cover cancellation on missing thread history (no silent fallback) and the console composer. The pre-change baseline had 10 failures and 2 fixture errors; these were audited before updating assertions.

Deployment waits for the current bridge response and native turn to finish. It changes public runtime files only, checks baseline hashes, backs up replaced code, restarts cc-limits only, verifies the unchanged console PID/thread/model/effort/cwd and new API/UI, and rolls back code if health checks fail. Account credentials, work profile settings, cxw and native console services are not part of the deployment file set.

## Reference styling restoration (3 November 2026)

Restored the approved first Overview palette, header, console tabs, account cards and quota bars. Additional account controls live in a native details menu; original DOM IDs and handlers are retained. Only cc_overview.py changes at runtime; account, model, profile and console backend modules are unchanged. Browser comparisons against the prior isolated UI confirmed the original controls, both optimization settings, selected-console input, profile/model controls, full-screen mode, menu state retention and 390–1920px layouts with no JavaScript errors or live API calls.

## Selected preview: full width and readable account controls (3 November 2026)

Preserved the selected reference layout, original action handlers and popup account menus. Removed the 1680px content cap; console and account groups use the browser width with small gutters. Account names are 16px, email 14px, and model/profile controls are larger. Browser verification compared original IDs and onclick handlers and exercised both provider switches, optimization, models, console input, settings, profiles, fullscreen and 320–2560px layouts. The isolated demo also supports test add/relogin/delete flows without OAuth or command execution and clearly identifies sample data. This presentation candidate is published to the protected preview only; production runtime files are unchanged.

## Collapsed pause status (3 November 2026)

Wrapped the native pause banner in a closed details/summary element. The row retains the original status, automatic-resume text and live countdown. The original reason, account chips and pause action stay inside; handlers and backend logic are unchanged. Expansion survives native render/data refreshes and resets after the banner disappears. Browser checks covered mouse, keyboard, touch, warning states, native mock pause off/on, countdown updates and widths 320–2560px without errors or live API calls. The protected preview has an explicit synthetic pause example at /cc-demo/?pause=1. Normal demo data and production runtime files are unchanged.

## First-screen console and active limits (3 November 2026)

Added two compact active-account summaries above the console from existing Claude snapshots and Codex rotation/account data, without additional polling. Used session/week quotas, missing values, stale/error labels and active-card links remain explicit. Header retains profile selection; native Codex model/settings, Claude model controls, refresh and general settings moved into a single management disclosure. The native pause banner now has a 30px one-line summary with full original title/details/actions inside. Complete console and composer fit at 1920×1080 and browser-height 980/900 variants. Browser checks retained existing IDs/handlers, exercised models/effort, settings, profiles, independent optimization, manual selection for both providers, console routing, missing/stale data, pause controls/keyboard, native fullscreen, responsive widths and touch. Published to the isolated protected demo only; production files and backend logic are unchanged. This compact summary follows the user's new explicit request and does not revive the cancelled mobile redesign.

## Consistent provider controls and visible reserve (3 November 2026)

Removed the Management disclosure. Each active-provider tile now contains matching model/effort and settings buttons; Claude's quick chooser uses the same radio/list components as Codex and calls the existing model/effort functions, including confirmation and supported-level restrictions. Full provider settings share panel/header/card/input/button styling, with original controls and callbacks retained. Codex thresholds are in its own panel; common appearance/update/backup options remain reachable from the header. Reserve keeps its original indicator/switch/settings handlers and is back in the header beside profile selection, without another header row. Existing account lists, optimization, console input and thin pause remain. Browser checks covered all 110 original IDs, both model/effort paths, provider and common settings, fake reserve confirmation/on/off, both account selections, profiles, console routing, fullscreen, pause, 320–2560px menus and touch. Full console and composer fit at Full HD and 980/900px browser heights. Only the protected demo is updated; production and backend files are unchanged. Demo reserve APIs are simulated and do not invoke an agent.

## Profile palette and comparison (3 November 2026)

Replaced the full-height profile drawer with a compact menu matching the provider panels. Existing radio nodes and native apply/confirmation/delete/history handlers are retained. Current profile appears first; cards show working mode, access and a concise description. Comparison reveals native flow/capability/limit information side by side and changes only client disclosure state. Search includes original descriptions and metadata, shows counts/empty state and resets correctly. Arrow/Home/End navigation, desktop search focus, focus/scroll retention across refresh and a touch layout without forced keyboard improve selection. Automatic Reserve and emergency controls retain their native behavior; main reserve is still visible. Browser checks exercised Full confirmation/cancel against fake APIs, custom delete, emergency information, comparison without POSTs, native Back/close, 320–2560px bounds and real touch emulation. The selected unified design remains the base. Published to the protected demo only; production profiles, backend and native console are unchanged.

Profile captions now put the actual lead before the executor: Codex → Claude for orchestrated work. Solo profiles explicitly say Codex / Codex Full · solo; the reserve names the actual Codex + Notion partnership. The same labels appear in cards, selection status and the header. Custom captions derive their leading roles from validated mode metadata and retain their original names. This changes display labels only; native IDs, apply/confirmation/delete handlers, account settings and backend files are unchanged. Browser checks covered captions, header consistency, old-name search, comparison, custom profiles and 320–1920px bounds with zero POSTs. Published to the demo only.

Service-mode completeness audit: the live API and pre-redesign baseline contain three ordinary profiles, automatic Reserve, and configured Emergency mode. The preview's missing emergency configured flag hid the native emergency card; restored a simulated configured emergency with test-only confirmation/on/off, and an explicit service section/count. Active emergency status is now reflected in the profile palette header. Real registry, profiles and services were not changed. Historical 1.25.28 had an Agent profile with separate delegation behavior; that profile is absent from the current pre-redesign baseline. Restoring that backend behavior or introducing Claude-led profiles requires identifying the user's intended missing variant rather than adding a misleading caption.

Fixed profile-search autofill hiding every card. The screenshot showed a browser-filled login in the search field and 0/3 matches. Reproduced the symptom on the prior demo, then isolated the query in a search-only form with autocomplete disabled, removed search autofocus, reset filters on each open, and made filtering use accepted user input instead of arbitrary browser-restored values. Native autofill state and unsolicited replacement events cannot overwrite a deliberate query; periodic data refresh also ignores uncommitted input values. Browser checks covered late/silent autofill, trusted input in Chrome's forced autofill pseudo-state, deliberate Cyrillic/keyboard search and clearing, Enter without POST/navigation, refresh/reopen, 320–1920px bounds and touch. Published preview verification passed with all profiles visible and no requests changing profiles or models. Production is unchanged.


## Mirrored Claude/Codex profile prototype (3 November 2026)

Added provider-specific profile/reserve controls to the active account tiles and a shared palette with clear Claude orange / Codex green tabs. Both sides contain the same three ordinary profiles and two service modes, capability/flow details, comparison, capability search and confirmations. Profile captions name the leader first; the paired scenario has exactly one leader. Reserve remains immediately visible for each side. Existing model/account/general settings and the console composer are retained. The mirror UI is capability-gated; an older backend continues to use the native Codex picker and reserve.

The reproducible `preview/` server and pure scenario module implement **demo state only**: reversible role changes, word-confirmed Full/emergency, reserve restoration, two-hour deadlines, revision conflicts and symmetric auto-reserve settings. Manual stop prevents automatic reactivation until recovery. They do not implement native console adapters, persistence, real limit eligibility, OS permissions or busy-turn coordination; approval of the preview must not be treated as a completed production integration.

Twelve pure scenario tests passed. Browser checks exercised both provider palettes, reversed leadership, Full cancellation, manual reserve/restore, emergency on/off, automatic options and confirmations, shared connector settings, model/effort preservation, search/autofill, keyboard, 320–2560px bounds and actual touch emulation. All profile mutations targeted mock profile endpoints only. The complete console/composer and active quotas fit on the first Full HD screen. No production runtime files or native console services were changed.

## Mirrored work profiles — production integration 1.27.0

Approved by Denis: «да отлично. делай релиз». The production candidate adds the
actual `/api/profiles` controller and native adapters, rather than installing the
demo's in-memory state as if it controlled real sessions.

- Durable provider registries and a recoverable transaction journal; five mirrored
  built-in scenarios per side, existing custom Codex profiles retained. One leader
  per pair, explicit executor and paused roles. Existing live Claude permissions
  are adopted as current settings; an explicit profile selection installs its
  hooks without relaunching either console at deployment.
- Native Codex uses its existing launch/session reader with explicit thread,
  model/effort/history and cwd. Managed role changes retain the same conversation
  across sandbox and cwd changes. Rotation and model changes are suspended during
  profile transitions and when the provider is paused.
- Claude resumes the exact session from its PID metadata, never the newest file.
  Launch arguments retain current model and effort, append role instructions and
  refresh the system-prompt snapshot. Later profile-driven launches use a separate
  systemd unit, so a panel restart does not own the native console lifetime.
  Restricted Claude profiles permit file operations in their workspace and project
  reads; command execution requires Full. Profile hooks block out-of-root paths,
  symlinks, other agents and unauthorized Notion calls; channel replies remain.
- Both directions use immutable, stored task text, human approval in the balance
  panel, and result feedback to the native leader. Full task scope needs a word.
  Interrupted/uncertain dispatches are not automatically replayed. Native Claude
  result parsing covers both end_turn and the locally observed stop_sequence.
- Mirrored manual/automatic reserve, stable fresh availability, unknown-data hold,
  manual-off suppression and restoration. Standalone Full suppresses automatic
  agent activation. Codex emergency retains its existing configured OS grants and
  duration, including the current manual-off-only configuration. Claude temporary
  Full lasts two hours; hooks reject tools at expiry and the active owner is
  interrupted before restoring its prior profile. Revoked emergency permissions
  are not re-granted during a failed console restoration.

Validation: 58 controller/routing/session tests, 77 existing console tests and
7 installer tests passed in isolated directories as the unprivileged user.
Separate real GNU screen/PTY checks used fake Codex and Claude executables; no
model or external-agent calls were made. They exercised exact conversation/model/
effort retention, profile changes and separate account history. Browser checks
used the real durable coordinator with fake native effects, including both task
approval directions, search/autofill, comparison, confirmations and 320–2560px
layouts/touch. A separate staged browser check used real read-only account and
console snapshots and an expected bootstrap registry, with all POSTs blocked.
Physical switching between two real authenticated Codex accounts remains untested
because only one account is currently connected.

Official references for explicit configuration and resume behavior:
[Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
[Codex resume](https://learn.chatgpt.com/docs/developer-commands?surface=cli),
[Claude CLI](https://code.claude.com/docs/en/cli-reference) and
[Claude permissions/hooks](https://code.claude.com/docs/en/permissions).
Installed native CLI help was also checked. No model migration was performed.

Deployment replaces only the listed public runtime modules after current Telegram
reply delivery and native idle, with baseline hashes, backups and rollback. Health
checks verify both unchanged native conversations/models/efforts, real mirrored
API, original controls and the actual served UI. Account credentials and console
commands are outside the installation file set. No remote push is authorized.
