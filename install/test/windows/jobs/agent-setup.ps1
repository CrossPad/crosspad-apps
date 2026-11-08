# Clean Windows 11: the installer leaves Claude Code with the CrossPad plugin.
#   1. fresh, unattended, no Claude Code: the AI step says so and goes on
#   2. Claude Code installed the way the installer's question installs it, plus
#      the hand-added `crosspad` (npx) an older installer registered
#   3. the installer again: the old server goes, the plugin comes, Claude Code
#      reaches the CrossPad tools from the project folder
# Under test, from the share when present: install.ps1 (else main on GitHub)
# and mcp-plugin\ (a crosspad-mcp checkout, else the plugin on GitHub).
# Every line of the result is PASS/FAIL, RESULT: last, in agent-setup.log.
$ErrorActionPreference = "Continue"
$S = "\\host.lan\Data"
$log = "$S\agent-setup.log"
"started $(Get-Date -Format o) as $env:USERNAME, PS $($PSVersionTable.PSVersion)" | Out-File $log
$fails = 0
function Check($ok, $what) {
    if ($ok) { "PASS $what" | Out-File -Append $log } else { "FAIL $what" | Out-File -Append $log; $script:fails++ }
}
function Refresh-Path { $env:Path = "$HOME\.local\bin;" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine") }

if (Test-Path "$S\token.txt") { $env:GH_TOKEN = (Get-Content "$S\token.txt" -Raw).Trim() }
$env:CROSSPAD_YES = "1"; $env:CROSSPAD_NO_TUI = "1"
if (Test-Path "$S\mcp-plugin\.claude-plugin\marketplace.json") {
    # A plugin root on a UNC path is not what a user has: test it from C:.
    Copy-Item -Recurse -Force "$S\mcp-plugin" C:\mcp-plugin
    $env:CROSSPAD_MCP_MARKETPLACE = "C:\mcp-plugin"
}
$script = if (Test-Path "$S\install.ps1") { Get-Content "$S\install.ps1" -Raw }
          else { Invoke-RestMethod https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 }
$script | Set-Content -Encoding UTF8 C:\install-under-test.ps1
function Install($name) {
    # The way the guide runs it: the script's text through iex.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content C:\install-under-test.ps1 -Raw | iex" *> "$S\agent-$name.log"
    Refresh-Path
    return (Get-Content "$S\agent-$name.log" -Raw)
}

$out = Install "1-fresh"
Check ($out -match "All set") "fresh install ends with All set"
Check ($out -match "CrossPad MCP server \d") "the MCP server installed into ~\.local\crosspad-mcp"
Check ($out -match "the MCP server starts and offers \d+ tools") "the installed server answers"
Check ($out -match "no Claude Code") "no Claude Code: noted, not installed under CROSSPAD_YES"
$cfg = Get-Content "$HOME\.config\crosspad-mcp\config.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
Check ($cfg.idf_root -eq "C:\CrossPad\firmware") "config.json idf_root = C:\CrossPad\firmware ($($cfg.idf_root))"
$vs = Get-Content C:\CrossPad\firmware\.vscode\mcp.json -Raw -ErrorAction SilentlyContinue
Check ($vs -match '"command": "node"') ".vscode\mcp.json starts the server with node"

# The installer's own command for Claude Code, then what an older installer added.
Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression *> "$S\agent-claude-install.log"
Refresh-Path
$ver = (claude --version 2>$null | Out-String).Trim()
Check ($ver -match "Claude Code") "Claude Code installed: $ver"
claude mcp add --scope user crosspad -e "CROSSPAD_IDF_ROOT=C:\CrossPad\firmware" -- npx -y crosspad-mcp-server@latest *> $null

$out = Install "2-with-claude"
Check ($out -match "All set") "second run ends with All set"
Check ($out -match "added by an older installer is gone") "the hand-added npx server is removed"
Check ($out -match "has the CrossPad plugin") "the plugin is installed"
Check ($out -match "reaches the CrossPad tools") "the installer saw the plugin's server connected"
$plugins = (claude plugin list 2>&1 | Out-String)
"--- claude plugin list`n$plugins" | Out-File -Append $log
Check ($plugins -match "crosspad@crosspad") "claude plugin list shows crosspad@crosspad"
Push-Location C:\CrossPad\firmware
$list = (claude mcp list 2>&1 | Out-String)
Pop-Location
"--- claude mcp list (C:\CrossPad\firmware)`n$list" | Out-File -Append $log
Check ($list -match "plugin:crosspad:crosspad:.*Connected") "Claude Code reaches the plugin's server from the project"
Check (-not ($list -match "(?m)^crosspad:.*npx")) "no second crosspad through npx"

Remove-Item "$S\token.txt" -Force -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable("GH_TOKEN", $null, "User")
"RESULT: $(if ($fails) { "FAIL ($fails)" } else { "PASS" })" | Out-File -Append $log
