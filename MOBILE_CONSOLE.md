# Mobile console controls and scrolling

On phone-sized screens and touch landscape layouts, the terminal gets its own
viewport. Zoom and fullscreen controls sit inside its upper right corner; Codex
stop, compact and new-session actions sit at the upper left. The buttons have
transparent backgrounds and no frames. The controls reserve a small area above
the terminal text, so they do not cover output or move with terminal history.
The existing nodes and handlers are moved rather than replaced.

On mobile, the active account tiles are always expanded directly below the console.
The compact summary and Expand/Collapse controls are hidden. The same live nodes
are moved, retaining both providers' model, settings, profile and reserve controls.
Desktop placement above the console and its open state are restored when changing
back to a desktop layout. Fullscreen hides the account tiles; normal mode restores
them below the console. The lower account list remains accessible.

Normal mobile navigation starts with the account page visible even if an old
console-only preference was saved. The saved value is retained; desktop startup
behavior is unchanged. The fullscreen button still enters and leaves console-only
mode explicitly. The legacy desktop account dock is hidden and inert on mobile.

Terminal history remains an independent scroll area. In normal mobile mode a
single-finger vertical drag starting at either history boundary is passed to the
page, allowing the user to reach the header and all account cards. Horizontal
drags, multi-touch and fullscreen terminal gestures retain their native behavior.
Console polling preserves the reader's history position. Fullscreen uses the
visual viewport height so the composer remains inside a reduced viewport.

Browser validation uses actual local GET snapshots and isolated POST responses.
It exercises touch scrolling of history and the outer page, the final account,
saved focus mode, normal/fullscreen transitions, transparent control positions,
zoom, provider tabs, preserved drafts and reduced viewport height. Stop, compact
and new-session handler payloads are checked without sending them to the running
server. Desktop placement and preferences, and the existing limit disclosures and
reset formats, are checked separately. Native processes and conversations are not
restarted by deployment.

The mobile profile picker is a top-aligned modal covering the visual viewport.
Its header and close action remain visible while the profile list scrolls inside.
The underlying page is fixed and inert while the picker is open; closing by the
close button, Escape or browser Back restores the page position and provider
button focus. Desktop positioning remains anchored to its provider button.
