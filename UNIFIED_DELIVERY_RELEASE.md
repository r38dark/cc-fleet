# Release1.28.5 — stand first, repair approved

The user approved the proposed delivery repair with a separate stand first.
The stand is complete. Continue with the guarded panel-only release; no additional
native-console restart is authorized or required.

Changed runtime files:

- cc_codex_bridge.py: prepare media on receipt; common ordered live input.
- cc_input_queue.py: bounded preparation workers, ordering, cancellation and errors.
- cc_limits.py: version only.
- CHANGELOG.json: release description.

The candidate install.sh and update_manifest.json both include cc_input_queue.py.
Native console code, private Screen5 binary, root cxw wrapper, profile/account
mechanics and settings are unchanged.

After approval, use the tested panel-only guarded release flow:

1. Recheck hashes against production1.28.4 and exact native identity/settings.
2. Snapshot current native PID/start time, thread, model/effort, account, cwd,
   sandbox/approval/MCP and bridge settings. Prepare backups of the four files.
3. Wait for delivered reply, native turn idle and bridge busy=false. Prepared
   inputs and pending error notifications participate in busy detection.
4. Stop only cc-limits.service, atomically install the candidate files, restart it.
5. Verify HTTP console, bridge/live_input, account/profile/model endpoints, same
   native PID/start/thread/settings, unchanged other runtime files and a browser
   read-only smoke check. Do not send a test prompt to the live model.
6. Roll back the four files and reload only the panel if validation fails.
7. Notify the same user/bot after verified success. Observe the user's next normal
   text/photo message for the first live round trip.

No native-console restart is required. Never stop cc-codex-console.service for
this release. Pending memory-only queue recovery after a crash is outside this
candidate's scope; the idle gate is required for installation.
