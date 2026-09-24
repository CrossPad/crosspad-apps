# FL Studio <-> CrossPad, end to end, on a Windows where CrossPad is installed
# and FL Studio (trial) is too. Every check is one PASS/FAIL line; the last
# line is RESULT. The board runs DAW Control; FL runs the CrossPad script.
param([string]$Log = "\\host.lan\Data\fl-check.log")
$ErrorActionPreference = "Continue"
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
function Hil($a) { (cmd /c "crosspad-hil $a" 2>&1) -join " " }
function Daw { Hil "cdc DAW_STATE" }
function Field($state, $name) { if ($state -match "\b$name=(\S+)") { $Matches[1] } else { "" } }
$script:fails = 0
function Check($ok, $what, $detail) {
    if ($ok) { "PASS $what" } else { "FAIL $what -- $detail"; $script:fails++ }
}
# Poll DAW_STATE until $cond holds or $seconds pass; returns the last state.
function WaitDaw([scriptblock]$cond, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do { $s = Daw; if (& $cond $s) { return $s }; Start-Sleep 2 } while ((Get-Date) -lt $deadline)
    return $s
}
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public class FlWin { public delegate bool P(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] static extern bool EnumWindows(P p, IntPtr l);
 [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
 public static int Close(uint want, string prefix) { int n = 0;
  EnumWindows((h, l) => { uint pid; GetWindowThreadProcessId(h, out pid);
   if (pid == want && IsWindowVisible(h)) { var t = new StringBuilder(256); GetWindowText(h, t, 256);
    if (t.ToString().StartsWith(prefix)) { PostMessage(h, 0x10, IntPtr.Zero, IntPtr.Zero); n++; } }
   return true; }, IntPtr.Zero);
  return n; } }
'@

& {
    "started $(Get-Date -Format o)"
    "== board"; Hil "devices"
    "APP: $(Hil 'cdc APP_START DawControl')"; Start-Sleep 3
    $s = Daw
    Check ((Field $s "running") -eq "1") "DAW Control runs on the board" $s

    $hw = "$([Environment]::GetFolderPath('MyDocuments'))\Image-Line\FL Studio\Settings\Hardware\CrossPad"
    # The installer puts the script there when FL is installed; nothing here copies it.
    $installed = Test-Path "$hw\device_CrossPad.py"
    Check $installed "the installer put FL's CrossPad script in place" "$hw\device_CrossPad.py is missing"
    $fl = Get-ChildItem "C:\Program Files\Image-Line" -Recurse -Filter FL64.exe | Select-Object -First 1
    Check ($null -ne $fl) "FL Studio is installed" "no FL64.exe under C:\Program Files\Image-Line"
    Get-Process FL64 -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 3
    $p = Start-Process $fl.FullName -PassThru

    # FL holds its script's MIDI output while the welcome window is open (the
    # board's hello arrives, FL's answer does not leave): close it as a user would.
    $closed = 0; $deadline = (Get-Date).AddSeconds(90)
    while ($closed -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep 3; $closed = [FlWin]::Close([uint32]$p.Id, "Welcome to FL Studio") }
    "welcome window closed: $closed"

    # 1. FL found the port by the script's supportedDevices and answered the hello.
    $s = WaitDaw { param($x) (Field $x "connected") -eq "1" } 120
    Check ((Field $s "connected") -eq "1" -and (Field $s "daw") -eq "1") "FL Studio is the board's host (auto-detected port)" $s
    # 2. FL painted the LCD rows: channel, pattern, tempo (right after its hello).
    $s = WaitDaw { param($x) $x -match 'row1="Pattern' -and $x -match 'row2="[0-9.]+ BPM"' } 10
    Check ($s -match 'row1="Pattern' -and $s -match 'row2="[0-9.]+ BPM"') "FL wrote the channel, pattern and tempo rows" $s
    "LEDs (keyboard): $(Hil 'cdc LED_STATE')"

    # 3. Double tap: the board switches to the control layout and tells FL.
    Hil "cdc IMU_GESTURE DOUBLE_TAP" | Out-Null
    $s = WaitDaw { param($x) (Field $x "mode") -eq "3" } 10
    Check ((Field $s "mode") -eq "3") "double tap puts DAW Control in control mode" $s
    "LEDs (control): $(Hil 'cdc LED_STATE')"

    # 4. Pad 0 is Play: FL starts, and its transport and beat come back.
    $beats0 = [int](Field (Daw) "beats")
    Hil "cdc PAD_PRESS 0 100" | Out-Null; Start-Sleep -Milliseconds 200; Hil "cdc PAD_RELEASE 0" | Out-Null
    $s = WaitDaw { param($x) (Field $x "transport") -ne "0" -and [int](Field $x "beats") -gt $beats0 + 2 } 15
    Check ((Field $s "transport") -ne "0" -and [int](Field $s "beats") -gt $beats0 + 2) "pad 0 starts FL, FL's beat reaches the board" "beats before: $beats0; $s"

    # 5. Pad 1 is Stop.
    Hil "cdc PAD_PRESS 1 100" | Out-Null; Start-Sleep -Milliseconds 200; Hil "cdc PAD_RELEASE 1" | Out-Null
    $s = WaitDaw { param($x) (Field $x "transport") -eq "0" } 10
    Check ((Field $s "transport") -eq "0") "pad 1 stops FL" $s

    # 6. Back to the keyboard layout.
    Hil "cdc IMU_GESTURE DOUBLE_TAP" | Out-Null
    $s = WaitDaw { param($x) (Field $x "mode") -eq "0" } 10
    Check ((Field $s "mode") -eq "0") "second double tap returns to the keyboard layout" $s

    # 7. FL going away is seen by the board.
    $p.CloseMainWindow() | Out-Null; Start-Sleep 5
    Get-Process -Id $p.Id -ErrorAction SilentlyContinue | Stop-Process -Force
    $s = WaitDaw { param($x) (Field $x "connected") -eq "0" } 15
    Check ((Field $s "connected") -eq "0") "the board notices FL has gone" $s

    if ($script:fails -eq 0) { "RESULT: PASS" } else { "RESULT: FAIL ($script:fails)" }
} *> $Log
