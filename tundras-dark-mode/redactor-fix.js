(function () {
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

  function styleFrame(iframe) {
    let doc;
    try {
      doc = iframe.contentDocument;
    } catch (e) {
      return; // cross-origin, not ours to touch
    }
    if (!doc || !doc.head && !doc.documentElement) return;
    if (doc.getElementById(STYLE_ID)) return;
    const style = doc.createElement("style");
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function scan() {
    document.querySelectorAll(".redactor_box iframe, iframe.redactor_editor").forEach(styleFrame);
  }

  scan();
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
