# Privacy Policy for Tundras Dark Mode

Last updated: 2026-09-15

## Summary

Tundras Dark Mode does not collect, store, transmit, or share any personal
data, browsing history, or user content. It changes how tundras.com looks. It
does not read what you type, does not track what you view, and does not send
anything anywhere.

## What the extension does

The extension injects a dark-themed stylesheet (`dark.css`) into pages on
`https://www.tundras.com/*`, and a small content script
(`redactor-fix.js`) styles the reply editor's iframe on that same site. A
toolbar button toggles the theme on and off. That is the entirety of its
function.

## Data collection

None. The extension:

* Does not collect any personal information (name, email, location, browsing
  history, form input, or anything else).
* Does not use analytics, telemetry, or crash reporting of any kind.
* Does not set cookies or use any other tracking technology.
* Does not make any network requests. It has no server, and no code path in
  the extension contacts one.
* Does not read the content of any page you visit or any text you type,
  beyond what is required to apply CSS to the page structure itself.

## Storage

The extension stores exactly one value locally on your device, using the
browser's built-in `storage.local` API: whether the theme is currently on or
off. This value never leaves your device, is never transmitted anywhere, and
is not shared with the developer or any third party.

## Permissions

The extension requests the following browser permissions, each used only for
the stated purpose:

| Permission | Why it is needed |
|---|---|
| `storage` | Remembers whether you last turned the theme on or off, locally on your device. |
| `scripting` | Injects and removes `dark.css` on tundras.com pages. This is how the theme is applied and how the toolbar toggle turns it off. |
| `tabs` | Detects when a tundras.com tab finishes loading or navigates, so the theme can be (re)applied without a visible flash of the original light theme. |
| `host_permissions` (`https://www.tundras.com/*`) | The extension only ever acts on this one domain. It has no access to, and makes no request to, any other website. |

## Third parties

None. No data is collected, so none is shared, sold, or transferred to any
third party, advertiser, or analytics provider.

## Children's privacy

The extension does not knowingly collect data from anyone, including
children, because it does not collect data from anyone at all.

## Changes to this policy

Any future change to this policy will be made as a normal update to this
file in the extension's public source repository, visible in the file's
version history.

## Contact

Questions or concerns about this extension can be raised as an issue on the
project's GitHub repository:
https://github.com/phxbeau/tundras-dark-mode/issues
