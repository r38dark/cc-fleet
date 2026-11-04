# Codex terminal RGB transport

The managed Codex console and cxw use a private GNU Screen 5.0.2:
/opt/cc-limits/terminal/screen-5.0.2/screen.
Its socket directory is the Codex user's codex_console/screen5, mode0700.
System /usr/bin/screen and Claude sessions are unchanged.

The private binary is an optional deployment dependency. If absent, new
installations use system Screen; do not enable truecolor in Screen4.
The Python module and cxw read the running session's transport metadata.
Installing the binary alone never switches a live session to a new client.
Changing server versions requires a coordinated idle restart with the same
explicit thread, model, effort, cwd, account and access settings.
Do not substitute resume --last for the saved thread ID.

Build provenance:

- GNU source: https://ftp.gnu.org/gnu/screen/screen-5.0.2.tar.gz
- Source SHA256: ca9a2c7e240919bc7ac12124593ae4529bb4eb5f7349d8857829b7e3f0b3b332
- Configure: --disable-pam --disable-utmp
- Binary SHA256 (this server): 0ac49ea0eb575ce42b45090c02b91c6d3952caa1c29aa0d8e34e27995f406717
- No setuid bits; installation mode0755, owned by root.
- COPYING, original source archive and BUILD.json are retained beside the binary.
- Development ncurses files were extracted into a work sysroot; no system
  Screen package was replaced and no package installation is required at runtime.

New Screen5 rc adds truecolor on; keep term screen-256color,
logfile flush1, and the existing Km mouse compatibility setting.
Validate actual RGB at physical PTY output. tput colors=256 alone does
not establish RGB support.

Preflight and postflight use inert PTYs to verify actual cxw RGB output,
fragmented SGR mouse events, Cyrillic and bracketed paste. Never send model
test prompts to the shared production conversation.

Deployment evidence: /home/codextrial/work/cc-termux-rgb_20261104.
