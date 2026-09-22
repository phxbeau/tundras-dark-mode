// The reply editor's text area is a same-origin about:blank iframe that the page
// builds with JavaScript. scripting.insertCSS matches frames by URL and skips
// about:blank, so dark.css never reaches it; this script writes a <style> into
// the iframe directly instead.
//
// That style has to follow the same on/off setting as the rest of the theme.
// The toolbar toggle only removes dark.css, so this script watches the stored
// setting itself: it styles editors only while enabled, and removes the style
// from every editor as soon as the theme is switched off.
(function () {
  const api = globalThis.browser ?? globalThis.chrome;
  const STYLE_ID = "tundras-dark-mode-iframe-style";
  const CSS = `
    html, body {
      background-color: rgb(37, 37, 37) !important;
      color: rgb(246, 246, 246) !important;
    }
    a, a:link, a:visited {
      color: rgb(143, 210, 255) !important;
    }
  `;
  const EDITORS = ".redactor_box iframe, iframe.redactor_editor";

  let enabled = false; // stay light until the stored setting says otherwise

  function frameDoc(iframe) {
    try {
      return iframe.contentDocument;
    } catch (e) {
      return null; // cross-origin, not ours to touch
    }
  }

  function styleFrame(iframe) {
    const doc = frameDoc(iframe);
    if (!doc || (!doc.head && !doc.documentElement)) return;
    if (doc.getElementById(STYLE_ID)) return;
    const style = doc.createElement("style");
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function unstyleFrame(iframe) {
    const doc = frameDoc(iframe);
    const style = doc && doc.getElementById(STYLE_ID);
    if (style) style.remove();
  }

  function sync() {
    document.querySelectorAll(EDITORS).forEach(enabled ? styleFrame : unstyleFrame);
  }

  // Editors are created (and re-created) after page load, e.g. when opening a
  // quick reply, so keep watching; only style them while the theme is on.
  new MutationObserver(() => {
    if (enabled) sync();
  }).observe(document.documentElement, { childList: true, subtree: true });

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !("enabled" in changes)) return;
    enabled = changes.enabled.newValue !== false;
    sync();
  });

  api.storage.local.get({ enabled: true }).then((stored) => {
    enabled = stored.enabled !== false;
    sync();
  });
})();
