Historical orchestrator rights, checked against cc_codex_bridge.py before this change:
- BUILTIN_PROFILES: orchestrator / mode=orchestrator / access=read / task_rights=dev.
- plan(): the leader uses workspace-write in exchange_dir, so it can create an outbox step and cannot use its sandbox to modify the project.
- Legacy take_draft(): requested rights pass through cap_rights(requested, task_rights). Default ceiling is dev (changes/commits on dev, production excluded by the step contract). Each step needs human confirmation.
- The follower is an existing native console; old legacy permissions were carried in task text. Do not describe this as an OS sandbox or claim that a Full follower loses all physical access outside dev. Full remains bounded by OS rights; no server accounts/keys/root rights are created by choosing Full.
- Mirrored ProfileTasks had lost the ceiling check. This candidate restores that dev ceiling, stores requested_rights, normalizes the approved text and preserves immutable step confirmation.
- Both orchestration directions preserve native model/effort/exact conversation. Leader and follower are mutually exclusive roles; no circular delegation.
