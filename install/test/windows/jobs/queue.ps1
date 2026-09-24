# Started by C:\runner.ps1 at logon (as run-test.ps1): runs every job.ps1 the
# host drops into \\host.lan\Data, one at a time, and keeps waiting. Output in
# job.out, then job.done. The file is looked up by name: a directory listing of
# the share stays stale after the host changes it (Samba does not break the
# client's cache for changes outside Samba).
# Jobs never go through the Run dialog: Defender reads a pasted
# "powershell -executionpolicy bypass -file ..." there as ClickFix and kills
# the whole process tree.
$S = "\\host.lan\Data"
while ($true) {
    if (Test-Path "$S\job.ps1") {
        Move-Item "$S\job.ps1" "$S\job-running.ps1" -Force
        powershell -NoProfile -ExecutionPolicy Bypass -File "$S\job-running.ps1" *> "$S\job.out"
        Remove-Item "$S\job-running.ps1" -Force
        "done $(Get-Date -Format o)" | Out-File "$S\job.done"
    }
    Start-Sleep 3
}
