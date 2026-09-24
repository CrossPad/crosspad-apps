@echo off
rem Runs at the end of the unattended Windows setup. The test runner starts at
rem every logon of the Docker user (HKLM Run, not RunOnce), so a disk restored
rem from the golden copy runs it too.
copy /Y C:\OEM\runner.ps1 C:\runner.ps1
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v CrossPadTest /t REG_SZ /d "powershell -NoProfile -WindowStyle Minimized -ExecutionPolicy Bypass -File C:\runner.ps1" /f
