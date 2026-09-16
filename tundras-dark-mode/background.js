// Chrome and Edge expose the extension APIs as `chrome`; Firefox exposes both
// but only `browser` is promise-based there. Prefer `browser`, fall back to
// `chrome` -- under MV3 Chrome's `chrome.*` also returns promises, so the same
// await-style code below works unchanged on all three browsers.
const api = globalThis.browser ?? globalThis.chrome;

const MATCH_URL = "https://www.tundras.com/*";
const URL_PREFIX = "https://www.tundras.com/";
const CSS_FILE = "dark.css";
// Inject as a USER-origin stylesheet, not the default AUTHOR origin.
// tundras.com sets some of its own colors with !important (e.g.
// `.navTabs { background-color: #D4E1EE !important }`) at the same specificity
// as ours. Author-origin injections tie-break by sheet order, and that order
// differs between engines: Firefox puts injected sheets last (we win), Chrome
// and Edge put them first (the page wins, and the nav bar stays light).
// A USER-origin !important declaration outranks any author !important in every
// engine, so this makes the theme deterministic across all three browsers.
// Safe here because effectively every declaration in dark.css is !important.
const CSS_ORIGIN = "USER";

// How many stacked copies to try to peel off when disabling (see applyToTab).
const STACK_GUARD = 3;

async function updateBadge(enabled) {
  await api.action.setBadgeText({ text: enabled ? "ON" : "OFF" });
  await api.action.setBadgeBackgroundColor({
    color: enabled ? "#2d7a2d" : "#7a2d2d",
  });
}

// The events that trigger a re-apply overlap: onInstalled/onStartup plus
// tabs.onUpdated firing for both "loading" and "complete". Those handlers run
// concurrently, so a bare remove-then-insert interleaves (both remove, then
// both insert) and the sheet stacks anyway. Chain every operation for a given
// tab so they can't overlap.
const tabQueues = new Map();

function serialize(tabId, fn) {
  const prev = tabQueues.get(tabId) || Promise.resolve();
  const next = prev.then(fn, fn);
  tabQueues.set(tabId, next.catch(() => {}));
  return next;
}

function applyToTab(tabId, enabled) {
  return serialize(tabId, async () => {
    const opts = { target: { tabId, allFrames: true }, files: [CSS_FILE], origin: CSS_ORIGIN };
    try {
      if (enabled) {
        // Remove before inserting so the sheet can never stack: insertCSS
        // appends a fresh copy every call, and two copies meant a single
        // removeCSS on toggle-off only peeled off one layer, leaving the page
        // still themed. removeCSS does not throw when nothing is injected.
        await api.scripting.removeCSS(opts);
        await api.scripting.insertCSS(opts);
      } else {
        // Peel off any copies an older build stacked before the rule above
        // existed. No-ops once it's clean.
        for (let i = 0; i < STACK_GUARD; i++) await api.scripting.removeCSS(opts);
      }
    } catch (e) {
      // Common and harmless: tab navigated away/closed before this resolved,
      // or a frame (e.g. a cross-origin iframe) can't be targeted.
    }
  });
}

async function isEnabled() {
  const { enabled = true } = await api.storage.local.get({ enabled: true });
  return enabled;
}

// Re-sync badge + already-open tabs. Only worth doing at install/startup:
// under Chrome's MV3 service worker this file re-runs every time the worker
// wakes, and re-running it on every wake would stack duplicate stylesheets.
async function syncAll() {
  const enabled = await isEnabled();
  await updateBadge(enabled);
  if (!enabled) return;
  const tabs = await api.tabs.query({ url: MATCH_URL });
  for (const tab of tabs) applyToTab(tab.id, true);
}

api.runtime.onInstalled.addListener(syncAll);
api.runtime.onStartup.addListener(syncAll);

api.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  // Fire on "loading" (as early as possible, right as navigation starts --
  // this is what actually avoids the light-theme flash) and again on
  // "complete" as a safety net for anything that loads/rewrites late.
  if (changeInfo.status !== "loading" && changeInfo.status !== "complete") return;
  if (!tab.url || !tab.url.startsWith(URL_PREFIX)) return;
  if (await isEnabled()) applyToTab(tabId, true);
});

api.action.onClicked.addListener(async () => {
  const newEnabled = !(await isEnabled());
  await api.storage.local.set({ enabled: newEnabled });
  await updateBadge(newEnabled);

  const tabs = await api.tabs.query({ url: MATCH_URL });
  for (const tab of tabs) applyToTab(tab.id, newEnabled);
});

api.tabs.onRemoved.addListener((tabId) => tabQueues.delete(tabId));
