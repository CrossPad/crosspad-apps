# Clean Windows 11 with the real CrossPad passed through: install as the guide
# says, then check what a user relies on — tools in a new terminal, VS Code and
# its settings, the MCP server, the board, and one whole Update my CrossPad.
$ErrorActionPreference = "Continue"
$S = "\\host.lan\Data"
$env:GH_TOKEN = (Get-Content "$S\token.txt" -Raw).Trim()
$env:CROSSPAD_YES = "1"; $env:CROSSPAD_NO_TUI = "1"
function Log($name) { "$S\board-$name.log" }
"started $(Get-Date -Format o)" | Out-File "$S\runner.log"
powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex' *> (Log "1-install")
"exit=$LASTEXITCODE" | Out-File -Append (Log "1-install")
# A new window: PATH exactly as the registry has it now.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
& { foreach ($t in "git", "python", "gh", "code", "node", "npx", "cptools") {
        $c = Get-Command $t -ErrorAction SilentlyContinue
        "{0,-8} {1}" -f $t, ($(if ($c) { $c.Source } else { "MISSING" })) }
    "== extensions"; cmd /c "code --list-extensions"
    "== settings.json"; Get-Content C:\CrossPad\.vscode\settings.json
    "== mcp.json"; Get-Content C:\CrossPad\.vscode\mcp.json } *> (Log "2-environment")
cmd /c "cptools doctor" *> (Log "3-doctor")
cmd /c "cptools device" *>> (Log "3-doctor")
cmd /c "cptools update-board" *> (Log "4-update-board")
"exit=$LASTEXITCODE" | Out-File -Append (Log "4-update-board")
Copy-Item C:\CrossPad\.crosspad\last-update.log "$S\board-last-update.log" -ErrorAction SilentlyContinue
Remove-Item "$S\token.txt" -Force
[Environment]::SetEnvironmentVariable("GH_TOKEN", $null, "User")
"done $(Get-Date -Format o)" | Out-File "$S\finished"
