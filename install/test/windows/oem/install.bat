@echo off
rem Runs at the end of the unattended Windows setup. The test runner starts at
rem every logon of the Docker user (HKLM Run, not RunOnce), so a disk restored
rem from the golden copy runs it too. It runs from C:\OEM, where the setup put
rem it: nothing of the bench's lies loose on C:\ beside what the installer makes.
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v CrossPadTest /t REG_SZ /d "powershell -NoProfile -WindowStyle Minimized -ExecutionPolicy Bypass -File C:\OEM\runner.ps1" /f
