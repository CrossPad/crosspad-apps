# FL Studio for the golden image: the trial installs without an account; it
# cannot save projects, which the tests never do.
$S = "\\host.lan\Data"
$ProgressPreference = "SilentlyContinue"
& {
    $exe = "$env:TEMP\flstudio_installer.exe"
    Invoke-WebRequest -UseBasicParsing "https://support.image-line.com/redirect/flstudio_win_installer" -OutFile $exe
    "downloaded $((Get-Item $exe).Length) bytes"
    Start-Process $exe -ArgumentList "/S" -Wait
    $fl = Get-ChildItem "C:\Program Files\Image-Line" -Recurse -Filter FL64.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($fl) { "FL64: $($fl.FullName)" } else { "FL64.exe NOT FOUND" }
} *> "$S\fl-install.log"
"done $(Get-Date -Format o)" | Out-File "$S\finished"
