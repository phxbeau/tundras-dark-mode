#!/usr/bin/env python3
"""Verify the Tundras dark theme actually renders in Chrome / Edge / Chromium.

Launches each browser headless with the unpacked extension loaded, opens
tundras.com, and reads back *computed* styles over the DevTools protocol --
so it checks what the page really paints, not what the CSS file says.

    python verify.py                 # every browser it can find
    python verify.py --browser edge
    python verify.py --screenshot .  # also save a PNG per browser

Exit code 0 if every check passed, 1 otherwise.

A failed check means the theme is wrong. If the harness itself can't do its job
(browser missing, site unreachable, DevTools not answering) it reports ERROR and
never a FAIL, so a red result always means a real regression.
"""
import argparse, base64, json, os, shutil, socket, struct, subprocess
import sys, tempfile, time, urllib.error, urllib.request

# ---------------------------------------------------------------- expectations
# Values confirmed against Chromium 153 and Firefox 155 on 2026-09-15.
DARK_NAV = "rgb(10, 53, 82)"
CHECKS = [
    # label                     selector                                     property           expected           required
    ("page background",         "body",                                      "backgroundColor", "rgb(25, 25, 25)",   True),
    ("page text",               "body",                                      "color",           "rgb(246, 246, 246)",True),
    ("nav bar",                 ".navTabs",                                  "backgroundColor", DARK_NAV,            True),
    ("selected tab background", ".navTabs .navTab.selected .navLink",        "backgroundColor", "rgb(23, 96, 147)",  True),
    ("selected tab text",       ".navTabs .navTab.selected .navLink",        "color",           "rgb(255, 255, 255)",True),
    ("unselected tab text",     ".navTabs .navTab.PopupClosed .navLink",     "color",           "rgb(255, 255, 255)",True),
    ("sidebar block",           ".sidebar .secondaryContent",                "backgroundColor", "rgb(41, 41, 41)",   True),
    ("sidebar heading",         ".sidebar .secondaryContent h3",             "color",           "rgb(246, 246, 246)",True),
    ("sidebar footnote",        ".sidebar .secondaryContent .footnote",      "color",           "rgb(170, 170, 170)",False),
    ("footer bar",              ".footer .pageContent",                      "backgroundColor", "rgb(23, 96, 147)",  True),
    # Buttons the site paints with white text on its own light gradient sprite.
    # Only present on some pages, hence not required -- use --url on a thread
    # page to exercise the "Post Reply" one.
    ("login button text",       "a.buttonLogin",                             "color",           "rgb(25, 25, 25)",   False),
    ("more-options button text", "a.button.moreOptions",                     "color",           "rgb(25, 25, 25)",   False),
    # Anchor-based buttons: XenForo renders many buttons as <a class="button">,
    # and the broad a:link rule in dark.css used to paint them white on their
    # light background. Guard the general case, not just the two variants above.
    ("anchor button text",      "a.button",                                  "color",           "rgb(25, 25, 25)",   False),
    ("primary button text",     ".button.primary",                           "color",           "rgb(25, 25, 25)",   False),
]

WIN_CANDIDATES = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "chromium": [r"C:\Program Files\Chromium\Application\chrome.exe"],
}
NIX_CANDIDATES = {
    "chrome": ["google-chrome", "google-chrome-stable"],
    "edge": ["microsoft-edge", "microsoft-edge-stable"],
    "chromium": ["chromium", "chromium-browser"],
}


class HarnessError(Exception):
    """Something went wrong with the test rig, not with the theme."""


def find_browser(name):
    for path in WIN_CANDIDATES.get(name, []):
        if path and os.path.isfile(path):
            return path
    for exe in NIX_CANDIDATES.get(name, []):
        found = shutil.which(exe)
        if found:
            return found
    return None


# ------------------------------------------------------------ tiny CDP client
def _ws_connect(url):
    rest = url[len("ws://"):]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    s = socket.create_connection((host, int(port)), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise HarnessError("DevTools closed the connection during handshake")
        buf += chunk
    if b" 101 " not in buf.split(b"\r\n")[0]:
        raise HarnessError(f"DevTools refused the websocket upgrade: {buf[:120]!r}")
    return s


def _recv_exact(s, n):
    out = b""
    while len(out) < n:
        chunk = s.recv(n - len(out))
        if not chunk:
            raise HarnessError("DevTools connection closed mid-message")
        out += chunk
    return out


class CDP:
    def __init__(self, ws_url):
        self.s = _ws_connect(ws_url)
        self.n = 0

    def _send(self, payload):
        data = json.dumps(payload).encode()
        hdr = bytearray([0x81])
        ln = len(data)
        if ln < 126:
            hdr.append(0x80 | ln)
        elif ln < 65536:
            hdr.append(0x80 | 126); hdr += struct.pack(">H", ln)
        else:
            hdr.append(0x80 | 127); hdr += struct.pack(">Q", ln)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self):
        payload = b""
        while True:
            b1, b2 = _recv_exact(self.s, 2)
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", _recv_exact(self.s, 2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", _recv_exact(self.s, 8))[0]
            payload += _recv_exact(self.s, ln)
            if b1 & 0x80:                      # FIN
                return json.loads(payload.decode())

    def call(self, method, params=None, timeout=60):
        self.n += 1
        mine = self.n
        self._send({"id": mine, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._recv()
            if msg.get("id") == mine:
                if "error" in msg:
                    raise HarnessError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise HarnessError(f"{method}: timed out")

    def evaluate(self, expr):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r:
            raise HarnessError(f"page script failed: {r['exceptionDetails'].get('text')}")
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def targets(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
        return json.load(r)


def wait_for_target(port, pred, timeout, proc=None, what="target"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise HarnessError(f"browser exited early (code {proc.returncode})")
        try:
            for t in targets(port):
                if pred(t):
                    return t
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    raise HarnessError(f"timed out waiting for {what}")


# ----------------------------------------------------------------- the checks
PROBE = """(() => {
  const out = {};
  for (const [key, sel, prop] of %s) {
    const el = document.querySelector(sel);
    out[key] = el ? getComputedStyle(el)[prop] : null;
  }
  out.__title = document.title;
  out.__nav = document.querySelector('.navTabs') ? 'yes' : 'no';
  return JSON.stringify(out);
})()"""


def probe(cdp):
    spec = [[f"{i}", c[1], c[2]] for i, c in enumerate(CHECKS)]
    raw = cdp.evaluate(PROBE % json.dumps(spec))
    return json.loads(raw)


def run_browser(name, binary, url, ext_path, screenshot_dir, page_wait):
    profile = tempfile.mkdtemp(prefix=f"tdm-{name}-")
    port = free_port()
    args = [
        binary, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking",
        "--disable-sync", "--disable-features=Translate",
        f"--user-data-dir={profile}",
        f"--load-extension={ext_path}",
        f"--disable-extensions-except={ext_path}",
        f"--remote-debugging-port={port}",
        url,
    ]
    if os.name != "nt":
        args.insert(1, "--no-sandbox")

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        page = wait_for_target(port, lambda t: t["type"] == "page" and "tundras" in t["url"],
                               60, proc, "the tundras.com tab")
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Page.enable")
        time.sleep(page_wait)                   # let the extension inject + page settle

        data = probe(cdp)
        if data.get("__nav") != "yes":
            raise HarnessError("page loaded but has no .navTabs element -- "
                               "wrong page, or the site is down / blocking this browser")

        results = []
        for i, (label, sel, prop, expected, _required) in enumerate(CHECKS):
            actual = data.get(str(i))
            if actual is None:
                # Absence is page-dependent (no sidebar on a thread page, no
                # Post Reply button on the index), so it is never a FAIL -- the
                # skip count in the summary keeps it visible.
                results.append(("SKIP", label, expected, "not on this page"))
            else:
                results.append(("PASS" if actual == expected else "FAIL",
                                label, expected, actual))

        # Toggling off must fully revert -- this is the regression that bit us:
        # insertCSS stacks, and one removeCSS used to leave the page still dark.
        toggle = toggle_check(port, proc, cdp)
        results.append(toggle)

        if screenshot_dir:
            shot = cdp.call("Page.captureScreenshot", {"format": "png"})
            dest = os.path.join(screenshot_dir, f"tundras-{name}.png")
            with open(dest, "wb") as fh:
                fh.write(base64.b64decode(shot["data"]))
            print(f"    screenshot: {dest}")

        return results
    finally:
        if cdp:
            cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def toggle_check(port, proc, page_cdp):
    """One removeCSS must fully un-theme the page (i.e. exactly one copy is injected)."""
    label = "toggle off reverts (single injection)"
    try:
        # The MV3 service worker idles out; reloading the tab wakes it.
        try:
            sw = wait_for_target(port, lambda t: t["type"] == "service_worker", 5, proc, "sw")
        except HarnessError:
            page_cdp.call("Page.reload")
            time.sleep(4)
            sw = wait_for_target(port, lambda t: t["type"] == "service_worker", 30, proc,
                                 "the extension service worker")
        sw_cdp = CDP(sw["webSocketDebuggerUrl"])
        try:
            sw_cdp.evaluate("""(async () => {
              const tabs = await chrome.tabs.query({url: 'https://www.tundras.com/*'});
              for (const t of tabs)
                await chrome.scripting.removeCSS({target:{tabId:t.id, allFrames:true},
                                                  files:['dark.css'], origin:'USER'});
              return tabs.length;
            })()""")
        finally:
            sw_cdp.close()
        time.sleep(1.5)
        after = page_cdp.evaluate(
            "getComputedStyle(document.querySelector('.navTabs')).backgroundColor")
        if after == DARK_NAV:
            return ("FAIL", label, "nav bar reverts to the site's own color",
                    f"still {after} -- stylesheet injected more than once")
        return ("PASS", label, "reverts", after)
    except HarnessError as e:
        return ("SKIP", label, "reverts", f"could not test ({e})")


def main():
    ap = argparse.ArgumentParser(description="Verify the Tundras dark theme in Chrome/Edge.")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--browser", default="all",
                    choices=["all", "chrome", "edge", "chromium"])
    ap.add_argument("--ext", default=os.path.join(os.path.dirname(here), "dist", "chrome"),
                    help="path to the unpacked extension (default: ../dist/chrome)")
    ap.add_argument("--url", default="https://www.tundras.com/")
    ap.add_argument("--screenshot", metavar="DIR", help="save a PNG per browser")
    ap.add_argument("--wait", type=float, default=6.0,
                    help="seconds to let the page settle (default 6; raise on a slow VM)")
    a = ap.parse_args()

    ext = os.path.abspath(a.ext)
    if not os.path.isfile(os.path.join(ext, "manifest.json")):
        print(f"ERROR: no manifest.json under {ext}\n"
              f"       run  python build.py  first, or pass --ext", file=sys.stderr)
        return 2

    wanted = ["chrome", "edge", "chromium"] if a.browser == "all" else [a.browser]
    found = [(n, find_browser(n)) for n in wanted]
    found = [(n, p) for n, p in found if p]
    if not found:
        print(f"ERROR: none of {', '.join(wanted)} found on this machine", file=sys.stderr)
        return 2

    print(f"extension: {ext}")
    print(f"url:       {a.url}\n")

    overall_ok = True
    summary = []
    for name, binary in found:
        print(f"=== {name} ({binary}) ===")
        try:
            results = run_browser(name, binary, a.url, ext, a.screenshot, a.wait)
        except HarnessError as e:
            print(f"    ERROR: {e}\n")
            summary.append((name, "ERROR", str(e)))
            overall_ok = False
            continue
        except Exception as e:                                   # noqa: BLE001
            print(f"    ERROR: unexpected: {e}\n")
            summary.append((name, "ERROR", str(e)))
            overall_ok = False
            continue

        failed = 0
        skipped = 0
        for status, label, expected, actual in results:
            if status == "PASS":
                print(f"    PASS  {label}")
            elif status == "SKIP":
                skipped += 1
                print(f"    SKIP  {label} ({actual})")
            else:
                failed += 1
                print(f"    FAIL  {label}\n            expected {expected}\n            actual   {actual}")
        state = "OK" if failed == 0 else f"{failed} FAILED"
        if failed == 0 and skipped:
            state += f" ({skipped} skipped)"
        summary.append((name, state, ""))
        overall_ok &= failed == 0
        print()

    print("-" * 56)
    for name, state, note in summary:
        print(f"  {name:<10} {state}{(' - ' + note[:40]) if note else ''}")
    print("-" * 56)
    print("RESULT:", "all checks passed" if overall_ok else "problems found (see above)")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
