# Active limits: disclosure and reset labels

The compact row has one plain-text Expand action inside its right edge. The native
summary handles pointer and keyboard activation. Expanded cards have one discreet
plain-text Collapse action aligned at the lower right; it returns focus to the summary.
Both controls have no arrows, borders, backgrounds, rounded corners or protruding tabs.
The heading is plain text, and there is no extra summary arrow or header button.
Exactly one disclosure action is visible in either state. Background updates
preserve the state, and expanded cards replace the compact summary.

All five-hour limit displays use time remaining (for example, «через 2 ч 30 мин»).
Weekly limits use only the reset date and time in Asia/Irkutsk, retaining the full
weekday name. The reset year is shown when it differs from the current year.
Start dates are no longer calculated or displayed. The same formatter is used
in the summary, expanded active cards and the account list. An unchanged snapshot
still refreshes the countdown every 15 seconds while the page is visible.

Validation: 36 existing fleet tests passed. A browser test over actual GET
snapshots, with server mutations blocked, checked repeated mouse and keyboard
open/close, preservation through refresh, UTC browser versus Irkutsk labels,
touch input, 360/390/1024/1440/1920 px widths, missing/invalid/expired resets,
next-year dates, unchanged-snapshot countdown updates and both providers' model
and profile menus. Candidate screenshots were inspected. Installation waits for
the active native turn and Telegram reply delivery; it reloads only the panel,
preserving native processes and the installed cxw reconnect hotfix.
