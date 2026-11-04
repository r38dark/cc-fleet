# Unified Telegram input — isolated candidate

Denis approved the delivery repair, with preparation and testing on a separate
stand first. The successful stand is complete; the guarded panel-only installation
waits for current reply delivery. Baseline: cc-fleet1.28.4, commit40bd4e5.

The same ordered input queue now accepts text, individual photos and albums.
Photos are downloaded in two background workers as soon as they arrive.
An album reserves its position on its first frame. Later text keeps its position
even if another image finishes downloading earlier. Prepared media becomes the
same caption-and-absolute-path input already understood by the native console.

The active console reader consumes every ready input. It never downloads a file
or waits for a Telegram error notification. A reply that has already completed
can be delivered while a photo is still loading; the photo then continues in the
same conversation as the next turn.

The 30-second preparation deadline covers media I/O only. It does not limit
model work, reserve profiles or account sessions. A failed image/album is
reported explicitly; subsequent text can proceed. Partial albums are deleted.
Stop/new invalidate old preparation work, including callbacks that finish late.
Profile pause gates continue to control console input.

Telegram progress indicators are preserved: upload while waiting for media,
typing during a model turn. Background uploads do not replace an active typing
indicator. Input transport retains the quiet Screen5 readbuf operation.

## Validation

- 129 targeted tests: queue ordering, two downloads, stop/new, failures/deadlines,
  album atomicity, native acknowledgement, reply-boundary races and the existing
  console/bridge/helper checks.
- run_stand.py: localhost Bot API, actual file downloads, actual attached
  Screen5 PTY, actual paste operation and JSONL result reader. The terminal
  application is an inert receiver, so there are no model or real Telegram calls.
- The stand uses production paste/poll/album timing defaults. See
  stand-results.json for measured timings, accepted inputs and request timeline.
- Same historical suite against baseline and candidate:142 cases.24 failures
  already exist on the baseline; candidate introduces no additional failures.
  These include removed profile/delegation expectations, old busy-image refusal
  expectations, and a historical worker-reference race. The raw comparison is
  retained in legacy-baseline.json and legacy-candidate.json.

Run locally:

    cd /home/codextrial/work/cc-unified-delivery_20261104/stage
    CC_CODEX_PROFILES=../test-profiles python3 -m unittest test_cc_input_queue test_cc_live_media test_cc_telegram_live test_cc_codex_console test_cc_cxw_helper -q
    cd ..
    python3 run_stand.py

## Scope and release

This changes message preparation and dispatch. It does not replace the native
Codex TUI, create another conversation or alter account/model/profile logic.
The existing private Screen5 and cxw entry remain in place.

Pending inputs are still in process memory, as in the baseline. This candidate
does not add durable recovery after a process crash. A production installation
must wait until both the native turn and bridge work are idle, then reload only
the panel/bridge. Snapshot and verify the native PID/thread/model/effort/Full.
Rollback must also preserve that native process.

The local HTTP/PTy proof establishes this transport path with an inert receiver;
it does not claim a live Telegram/model round trip. Such observation follows
only an approved release and the user's next normal message.
