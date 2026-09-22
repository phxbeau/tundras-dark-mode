<#
.SYNOPSIS
    Verify the Tundras dark theme renders correctly in Chrome and Edge on Windows.

.DESCRIPTION
    Launches each browser headless with the unpacked extension loaded, opens
    tundras.com, and reads back *computed* styles over the DevTools protocol, so
    it checks what the page actually paints rather than what the CSS file says.

    Needs nothing installed beyond the browsers themselves -- Windows PowerShell
    5.1 is enough.

    A FAIL means the theme is wrong. If the harness itself cannot do its job
    (browser missing, site unreachable, DevTools not answering) it reports ERROR
    instead, so a FAIL always means a real regression.

.PARAMETER Browser
    all (default), chrome, or edge.

.PARAMETER ExtensionPath
    The unpacked extension. Defaults to ..\dist\chrome relative to this script.

.PARAMETER Screenshot
    Directory to save a PNG per browser.

.EXAMPLE
    .\Verify-Theme.ps1
.EXAMPLE
    .\Verify-Theme.ps1 -Browser edge -Screenshot .
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'chrome', 'edge')] [string] $Browser = 'all',
    [string] $ExtensionPath,
    [string] $Url = 'https://www.tundras.com/',
    [string] $Screenshot,
    [double] $Wait = 6.0
)

$ErrorActionPreference = 'Stop'

# ------------------------------------------------------------- expectations --
$DarkNav = 'rgb(10, 53, 82)'
$Checks = @(
    @{ Label = 'page background';         Sel = 'body';                                   Prop = 'backgroundColor'; Want = 'rgb(25, 25, 25)';    Required = $true  }
    @{ Label = 'page text';               Sel = 'body';                                   Prop = 'color';           Want = 'rgb(246, 246, 246)'; Required = $true  }
    @{ Label = 'nav bar';                 Sel = '.navTabs';                               Prop = 'backgroundColor'; Want = $DarkNav;             Required = $true  }
    @{ Label = 'selected tab background'; Sel = '.navTabs .navTab.selected .navLink';     Prop = 'backgroundColor'; Want = 'rgb(23, 96, 147)';   Required = $true  }
    @{ Label = 'selected tab text';       Sel = '.navTabs .navTab.selected .navLink';     Prop = 'color';           Want = 'rgb(255, 255, 255)'; Required = $true  }
    @{ Label = 'unselected tab text';     Sel = '.navTabs .navTab.PopupClosed .navLink';  Prop = 'color';           Want = 'rgb(255, 255, 255)'; Required = $true  }
    @{ Label = 'sidebar block';           Sel = '.sidebar .secondaryContent';             Prop = 'backgroundColor'; Want = 'rgb(41, 41, 41)';    Required = $true  }
    @{ Label = 'sidebar heading';         Sel = '.sidebar .secondaryContent h3';          Prop = 'color';           Want = 'rgb(246, 246, 246)'; Required = $true  }
    @{ Label = 'sidebar footnote';        Sel = '.sidebar .secondaryContent .footnote';   Prop = 'color';           Want = 'rgb(170, 170, 170)'; Required = $false }
    @{ Label = 'footer bar';              Sel = '.footer .pageContent';                   Prop = 'backgroundColor'; Want = 'rgb(23, 96, 147)';   Required = $true  }
    # Buttons the site paints with white text on its own light gradient sprite.
    # Only on some pages -- use -Url on a thread page to exercise "Post Reply".
    @{ Label = 'login button text';       Sel = 'a.buttonLogin';                          Prop = 'color';           Want = 'rgb(25, 25, 25)';    Required = $false }
    @{ Label = 'more-options button text';Sel = 'a.button.moreOptions';                   Prop = 'color';           Want = 'rgb(25, 25, 25)';    Required = $false }
    # Anchor-based buttons: XenForo renders many buttons as <a class="button">,
    # and the broad a:link rule in dark.css used to paint them white on their
    # light background. Guard the general case, not just the two above.
    @{ Label = 'anchor button text';      Sel = 'a.button';                               Prop = 'color';           Want = 'rgb(25, 25, 25)';    Required = $false }
    @{ Label = 'primary button text';     Sel = '.button.primary';                        Prop = 'color';           Want = 'rgb(25, 25, 25)';    Required = $false }
    # Text fields kept XenForo's white background while their text was forced
    # white. Use the header search box; #loginBar has its own navy fields.
    @{ Label = 'text field background';   Sel = '#QuickSearchQuery';                      Prop = 'backgroundColor'; Want = 'rgb(37, 37, 37)';    Required = $false }
    @{ Label = 'text field text';         Sel = '#QuickSearchQuery';                      Prop = 'color';           Want = 'rgb(246, 246, 246)'; Required = $false }
)

function Find-Browser([string] $Name) {
    $paths = switch ($Name) {
        'chrome' { @(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") }
        'edge'   { @(
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") }
    }
    foreach ($p in $paths) { if ($p -and (Test-Path -LiteralPath $p)) { return $p } }
    # Fall back to the registry's recorded install location.
    $key = if ($Name -eq 'chrome') { 'chrome.exe' } else { 'msedge.exe' }
    foreach ($root in 'HKLM:\SOFTWARE', 'HKLM:\SOFTWARE\WOW6432Node') {
        $rp = "$root\Microsoft\Windows\CurrentVersion\App Paths\$key"
        if (Test-Path $rp) {
            $v = (Get-ItemProperty $rp).'(default)'
            if ($v -and (Test-Path -LiteralPath $v)) { return $v }
        }
    }
    return $null
}

function Get-FreePort {
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $l.Start(); $port = $l.LocalEndpoint.Port; $l.Stop()
    return $port
}

# ------------------------------------------------------ minimal CDP over WS --
class Cdp {
    [System.Net.WebSockets.ClientWebSocket] $Ws
    [int] $N = 0

    Cdp([string] $WsUrl) {
        $this.Ws = [System.Net.WebSockets.ClientWebSocket]::new()
        $this.Ws.ConnectAsync([Uri]$WsUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    }

    [object] Call([string] $Method, [hashtable] $Params) {
        $this.N++
        $mine = $this.N
        $body = @{ id = $mine; method = $Method; params = $Params } | ConvertTo-Json -Depth 10 -Compress
        $bytes = [Text.Encoding]::UTF8.GetBytes($body)
        $this.Ws.SendAsync([ArraySegment[byte]]::new($bytes),
            [System.Net.WebSockets.WebSocketMessageType]::Text, $true,
            [Threading.CancellationToken]::None).GetAwaiter().GetResult()

        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            $sb = [Text.StringBuilder]::new()
            do {
                $buf = [ArraySegment[byte]]::new([byte[]]::new(65536))
                $r = $this.Ws.ReceiveAsync($buf, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
                [void]$sb.Append([Text.Encoding]::UTF8.GetString($buf.Array, 0, $r.Count))
            } while (-not $r.EndOfMessage)
            $msg = $sb.ToString() | ConvertFrom-Json
            if ($msg.id -eq $mine) {
                if ($msg.PSObject.Properties.Name -contains 'error' -and $msg.error) {
                    throw "HARNESS: $Method failed: $($msg.error | ConvertTo-Json -Compress)"
                }
                return $msg.result
            }
        }
        throw "HARNESS: $Method timed out"
    }

    [object] Evaluate([string] $Expr) {
        $r = $this.Call('Runtime.evaluate',
            @{ expression = $Expr; returnByValue = $true; awaitPromise = $true })
        if ($r.PSObject.Properties.Name -contains 'exceptionDetails' -and $r.exceptionDetails) {
            throw "HARNESS: page script failed: $($r.exceptionDetails.text)"
        }
        return $r.result.value
    }

    [void] Close() { try { $this.Ws.Dispose() } catch { } }
}

function Wait-Target([int] $Port, [scriptblock] $Pred, [int] $TimeoutSec, $Proc, [string] $What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($Proc -and $Proc.HasExited) { throw "HARNESS: browser exited early (code $($Proc.ExitCode))" }
        try {
            $list = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/list" -TimeoutSec 5
            foreach ($t in $list) { if (& $Pred $t) { return $t } }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "HARNESS: timed out waiting for $What"
}

function Invoke-BrowserCheck([string] $Name, [string] $Binary, [string] $Ext) {
    $profileDir = Join-Path ([IO.Path]::GetTempPath()) ("tdm-$Name-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $null = New-Item -ItemType Directory -Path $profileDir -Force
    $port = Get-FreePort
    $args = @(
        '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
        '--disable-background-networking', '--disable-sync', '--disable-features=Translate',
        "--user-data-dir=$profileDir", "--load-extension=$Ext",
        "--disable-extensions-except=$Ext", "--remote-debugging-port=$port", $Url
    )
    $proc = Start-Process -FilePath $Binary -ArgumentList $args -PassThru -WindowStyle Hidden
    $cdp = $null
    try {
        $page = Wait-Target $port { param($t) $t.type -eq 'page' -and $t.url -like '*tundras*' } 60 $proc 'the tundras.com tab'
        $cdp = [Cdp]::new($page.webSocketDebuggerUrl)
        [void]$cdp.Call('Page.enable', @{})
        Start-Sleep -Seconds $Wait

        if ($cdp.Evaluate("document.querySelector('.navTabs') ? 'yes' : 'no'") -ne 'yes') {
            throw 'HARNESS: page loaded but has no .navTabs element -- wrong page, or the site is down / blocking this browser'
        }

        $results = @()
        foreach ($c in $Checks) {
            $expr = "(() => { const e = document.querySelector('$($c.Sel)'); return e ? getComputedStyle(e)['$($c.Prop)'] : null; })()"
            $actual = $cdp.Evaluate($expr)
            if ($null -eq $actual) {
                # Absence is page-dependent (no sidebar on a thread page, no
                # Post Reply button on the index), so it is never a FAIL -- the
                # skip count in the summary keeps it visible.
                $results += @{ Status = 'SKIP'; Label = $c.Label; Want = $c.Want; Got = 'not on this page' }
            } else {
                $results += @{ Status = $(if ($actual -eq $c.Want) { 'PASS' } else { 'FAIL' }); Label = $c.Label; Want = $c.Want; Got = $actual }
            }
        }

        # Switch the theme off the way the toolbar button does, then check that both
        # the page and the reply editor revert. The editor is an about:blank iframe
        # the page builds itself, styled by redactor-fix.js rather than dark.css, so
        # it must follow the stored on/off setting separately. One removeCSS must
        # also fully un-theme the page (exactly one copy of the stylesheet injected).
        $tLabel = 'toggle off reverts page and editor'
        $makeEditor = @'
(() => {
  if (document.getElementById('probeEditor')) return 1;
  const box = document.createElement('div'); box.className = 'redactor_box'; box.id = 'probeEditor';
  const f = document.createElement('iframe'); f.className = 'redactor_editor';
  box.appendChild(f); document.querySelector('#content .pageContent').appendChild(box);
  f.contentDocument.body.innerHTML = '<p>Write your reply...</p>';
  return 1;
})()
'@
        try {
            [void]$cdp.Evaluate($makeEditor); Start-Sleep -Milliseconds 1500
            $sw = $null
            try { $sw = Wait-Target $port { param($t) $t.type -eq 'service_worker' } 5 $proc 'sw' }
            catch {
                [void]$cdp.Call('Page.reload', @{}); Start-Sleep -Seconds 4
                [void]$cdp.Evaluate($makeEditor); Start-Sleep -Milliseconds 1500
                $sw = Wait-Target $port { param($t) $t.type -eq 'service_worker' } 30 $proc 'the extension service worker'
            }
            $swCdp = [Cdp]::new($sw.webSocketDebuggerUrl)
            try {
                # body of api.action.onClicked in background.js
                $nowOn = $swCdp.Evaluate(@'
(async () => {
  const newEnabled = !(await isEnabled());
  await api.storage.local.set({ enabled: newEnabled });
  await updateBadge(newEnabled);
  const tabs = await api.tabs.query({ url: MATCH_URL });
  for (const t of tabs) await applyToTab(t.id, newEnabled);
  return newEnabled;
})()
'@)
            } finally { $swCdp.Close() }
            if ($nowOn) {
                $results += @{ Status = 'SKIP'; Label = $tLabel; Want = 'reverts'; Got = 'theme was already off before the toggle' }
            } else {
                Start-Sleep -Milliseconds 1500
                $nav = $cdp.Evaluate("getComputedStyle(document.querySelector('.navTabs')).backgroundColor")
                $editor = $cdp.Evaluate("(() => { const f = document.querySelector('#probeEditor iframe'); return f ? getComputedStyle(f.contentDocument.body).backgroundColor : null; })()")
                $problems = @()
                if ($nav -eq $DarkNav) { $problems += "nav bar still $nav (stylesheet injected more than once)" }
                if ($editor -and $editor -ne 'rgba(0, 0, 0, 0)') { $problems += "reply editor still $editor (redactor-fix.js ignored the setting)" }
                if ($problems.Count -gt 0) {
                    $results += @{ Status = 'FAIL'; Label = $tLabel; Want = "page and editor revert to the site's own colours"; Got = ($problems -join '; ') }
                } else {
                    $results += @{ Status = 'PASS'; Label = $tLabel; Want = 'reverts'; Got = "nav $nav, editor $editor" }
                }
            }
        } catch {
            $results += @{ Status = 'SKIP'; Label = $tLabel; Want = 'reverts'; Got = "could not test ($($_.Exception.Message))" }
        }

        if ($Screenshot) {
            $shot = $cdp.Call('Page.captureScreenshot', @{ format = 'png' })
            $dest = Join-Path $Screenshot "tundras-$Name.png"
            [IO.File]::WriteAllBytes($dest, [Convert]::FromBase64String($shot.data))
            Write-Host "    screenshot: $dest"
        }
        return $results
    } finally {
        if ($cdp) { $cdp.Close() }
        try { if (-not $proc.HasExited) { $proc.Kill() } } catch { }
        Start-Sleep -Milliseconds 500
        Remove-Item -LiteralPath $profileDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --------------------------------------------------------------------- main --
if (-not $ExtensionPath) {
    $ExtensionPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\chrome'
}
$ExtensionPath = (Resolve-Path -LiteralPath $ExtensionPath -ErrorAction SilentlyContinue).Path
if (-not $ExtensionPath -or -not (Test-Path (Join-Path $ExtensionPath 'manifest.json'))) {
    Write-Host "ERROR: no manifest.json under the extension path." -ForegroundColor Red
    Write-Host "       run  python build.py  first, or pass -ExtensionPath"
    exit 2
}
if ($Screenshot) { $null = New-Item -ItemType Directory -Path $Screenshot -Force }

$wanted = if ($Browser -eq 'all') { @('chrome', 'edge') } else { @($Browser) }
$found = @()
foreach ($b in $wanted) {
    $p = Find-Browser $b
    if ($p) { $found += , @($b, $p) } else { Write-Host "note: $b not found on this machine" -ForegroundColor DarkYellow }
}
if ($found.Count -eq 0) { Write-Host "ERROR: none of $($wanted -join ', ') found" -ForegroundColor Red; exit 2 }

Write-Host "extension: $ExtensionPath"
Write-Host "url:       $Url`n"

$allOk = $true
$summary = @()
foreach ($pair in $found) {
    $name, $bin = $pair
    Write-Host "=== $name ($bin) ===" -ForegroundColor Cyan
    try {
        $results = Invoke-BrowserCheck $name $bin $ExtensionPath
    } catch {
        Write-Host "    ERROR: $($_.Exception.Message)`n" -ForegroundColor Red
        $summary += , @($name, 'ERROR'); $allOk = $false; continue
    }
    $failed = 0
    $skipped = 0
    foreach ($r in $results) {
        switch ($r.Status) {
            'PASS' { Write-Host "    PASS  $($r.Label)" -ForegroundColor Green }
            'SKIP' { $skipped++; Write-Host "    SKIP  $($r.Label) ($($r.Got))" -ForegroundColor DarkGray }
            default {
                $failed++
                Write-Host "    FAIL  $($r.Label)" -ForegroundColor Red
                Write-Host "            expected $($r.Want)"
                Write-Host "            actual   $($r.Got)"
            }
        }
    }
    $state = if ($failed -eq 0) { 'OK' } else { "$failed FAILED" }
    if ($failed -eq 0 -and $skipped -gt 0) { $state += " ($skipped skipped)" }
    $summary += , @($name, $state)
    if ($failed -ne 0) { $allOk = $false }
    Write-Host ''
}

Write-Host ('-' * 56)
foreach ($s in $summary) { Write-Host ("  {0,-10} {1}" -f $s[0], $s[1]) }
Write-Host ('-' * 56)
if ($allOk) { Write-Host 'RESULT: all checks passed' -ForegroundColor Green; exit 0 }
else { Write-Host 'RESULT: problems found (see above)' -ForegroundColor Red; exit 1 }
