# cxw: keep the terminal attached across a new conversation

The balancer's new-session action intentionally replaces the Codex Screen server.
Previously cxw used exec to become that server's attach client, so closing the
server returned the user to their SSH shell.

cxw now supervises the attach client. When Screen exits, it checks the saved
new-session intent or a replacement server PID, then waits up to 15 seconds for
the replacement. It resolves the binary and socket directory again before
reattaching. Ctrl+A, D leaves the command when the original server is still
alive; an explicit stop without a replacement exits immediately. Signals end
the client. A failed restart produces a bounded, visible error.

Only the cxw branch of cc-cmd changes. Native session, bridge, permissions,
conversation selection and settings are unchanged. No service restart is needed
for installation. An attachment made with the old executable must be detached
and opened with cxw once to load the supervisor.

Validation:

    python3 -m unittest test_cc_cmd test_cc_cxw_helper test_cc_codex_terminal -q
    python3 test_cc_cxw_reconnect_pty.py
    sudo python3 test_cc_cxw_reconnect_pty.py --user codextrial

The standalone PTY test uses actual Screen 5, isolated socket directories and
inert input receivers. It verifies a delayed and an immediate replacement with
the same cxw process, RGB, exact Unicode/paste/mouse input, deliberate detach,
explicit stop, failed startup and termination signals. No model or Telegram
request is made. --base /opt/cc-limits tests the installed client; --output PATH
saves the result. --screen PATH selects a different Screen 5 installation.
