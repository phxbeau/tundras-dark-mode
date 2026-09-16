# Tundras.com Dark Mode

Unofficial dark theme for tundras.com, adapted from TacomaWorld's dark style
(both sites run XenForo). Runs on Firefox, Chrome, Edge and Chromium.

## Layout

    tundras-dark-mode/     single shared source (manifest.json is the Firefox flavour)
    build.py               emits per-browser packages into dist/
    dist/
      tundras-dark-mode-firefox.xpi
      chrome/                          unpacked, for "Load unpacked"
      tundras-dark-mode-chrome.zip     same files, zipped

`tundras-dark-mode.xpi` in the project root is legacy (v1.3.1, pre-dating the
build script). The active builds all come from `dist/`; it is kept only for
reference.

Build with:

    python3 build.py

## Installing

**Firefox** — `about:addons` → gear icon → *Install Add-on From File…* →
`dist/tundras-dark-mode-firefox.xpi`. For a quick unsigned test instead use
`about:debugging#/runtime/this-firefox` → *Load Temporary Add-on…* (goes away on
restart).

**Chrome / Chromium** — `chrome://extensions` → enable *Developer mode* →
*Load unpacked* → select `dist/chrome/`.

**Edge (incl. Windows Server 2025)** — `edge://extensions` → enable
*Developer mode* (left sidebar) → *Load unpacked* → select `dist/chrome/`.
Edge is Chromium-based and uses the same build as Chrome; nothing Edge-specific
is needed.

> Unpacked extensions load from disk, so copy `dist/chrome/` to the VM rather
> than pointing at a network share it may not be able to read.

## Toggling

Click the toolbar icon to turn the theme on/off. The badge reads `ON`/`OFF` and
the state persists in `storage.local`.

## Two cross-browser gotchas worth remembering

**1. Inject as USER origin, not AUTHOR.** tundras.com sets some of its own
colors with `!important` at the same specificity as ours, e.g.
`.navTabs { background-color: #D4E1EE !important }`. Author-origin injections
tie-break on stylesheet order, and engines disagree about that order: Firefox
puts injected sheets last (we win) while Chrome and Edge put them first (the
page wins and the nav bar stays light blue). `origin: "USER"` outranks any
author `!important` everywhere, which is why it is set in `background.js`.
This is safe only because effectively every declaration in `dark.css` is
`!important` — a USER-origin rule *without* `!important` would lose to the page.

**2. insertCSS stacks, and the calls interleave.** `tabs.onUpdated` fires for
both `loading` and `complete`, and `insertCSS` appends a fresh copy each time
while `removeCSS` peels off only one. Two copies meant toggling the theme off
left the page still dark. `removeCSS` is a safe no-op when nothing is injected,
so `applyToTab` always removes before inserting — but that pair is not atomic,
and the concurrent handlers interleaved (both removed, then both inserted) and
stacked anyway. Operations are now chained per tab via `serialize()`.

## Testing

Two equivalent harnesses live in `test/`. Both launch each browser headless with
the unpacked extension, open the site, and read back **computed** styles over the
DevTools protocol — so they check what the page actually paints, not what the
CSS says. Both own the browser they start and terminate only that process.

    python test/verify.py                      # every browser found
    python test/verify.py --browser edge
    python test/verify.py --screenshot .
    python test/verify.py --url https://www.tundras.com/threads/<some-thread>/

On Windows, where Python may not be installed, use the PowerShell port instead
(Windows PowerShell 5.1 is enough — no modules to install):

    .\test\Verify-Theme.ps1
    .\test\Verify-Theme.ps1 -Browser edge -Screenshot .

Exit code is 0 when everything passed, 1 on failures, 2 on a bad invocation.

A check that can't run reports SKIP, not FAIL: the sidebar doesn't exist on a
thread page and the Post Reply button doesn't exist on the index, so absence is
page-dependent rather than a regression. The skip count is shown in the summary
so a wall of SKIPs can't quietly hide a selector that stopped matching. If the
harness itself can't do its job (browser missing, site unreachable, DevTools not
answering) it reports ERROR — so a FAIL always means a real regression.

Both scripts include a guard for the injection bug described above: they call
`removeCSS` once and assert the page fully reverts, which fails if the sheet is
ever stacked more than once.

> `verify.py` has been run against Chromium and its failure modes exercised
> deliberately (reverting to AUTHOR origin, and removing the stacking guard —
> both were caught). The PowerShell file is a transcription of that same logic
> and has **not** been executed; run it once against a known-good build first, so
> a harness problem isn't mistaken for a theme regression.

## Known-unfixed contrast spots

A handful of rules in `dark.css` still use dark text because they sit on
backgrounds the stylesheet never darkens, so the site's own light background
shows through and the dark text is correct there. Verified examples:
`.bbCodeBlock .type` (light lavender `rgb(225,228,242)`), `#vendorinfo`,
`.relprodvisual .relprodpopuphighlight a`.

Unverified — they never appeared on the pages checked, so it is not known
whether their background is light or dark: `.heading` / `.xenForm .formHeader`,
`.dataTable caption`, `#calcurrent`, `.discussionListFilters *`,
`.thread_view .threadAlerts *`. Check the real background before "fixing" the
text color on any of these.

The reverse case also exists and is fixed: `.buttonLogin` ("Post Reply") and
`.button.moreOptions` ("More...") are buttons the site paints with **white** text
on its own light gradient sprite. The theme never touched them, so they rendered
at 1.73:1 and 1.36:1. Because that background is a sprite image rather than a
color, the fix darkens the text instead — which is what `.button` /
`input.button` already do on this site. Both engines computed identical values
before and after, so this was never a Chromium-specific fault.
