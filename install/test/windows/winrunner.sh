#!/bin/bash
# A Windows GitHub Actions runner on this Linux machine: a dockurr/windows VM
# made from wintest.sh's clean disk, with the runner as a Windows service.
# For private repositories, whose hosted Windows minutes are paid (public ones
# run windows-latest for free, and a self-hosted runner there would run fork
# pull requests' code on this machine).
#   winrunner.sh create   copy the golden disk, start the VM, install Git and
#                         register the runner (asks gh for a 1 h token)
#   winrunner.sh start    start the VM as it was left (the runner comes up by itself)
#   winrunner.sh stop
#   winrunner.sh job FILE.ps1   run FILE in the VM (after start), print its output
#   winrunner.sh on|off   CI_WIN_RUNNER=crosspad-win on the repository / unset
#                         (off before powering the machine down: GitHub never
#                         falls back from a self-hosted label to a hosted runner)
#   winrunner.sh status
# The workflow reads it as runs-on: ${{ vars.CI_WIN_RUNNER || 'windows-latest' }}.
# Disk and share in $WINRUNNER_HOME (default /mnt/backup/winrunner, / is the
# full one); noVNC on 127.0.0.1:8007 (wintest.sh keeps 8006, both can run).
set -e
R="$(cd "$(dirname "$0")" && pwd)"
W="${WINRUNNER_HOME:-/mnt/backup/winrunner}"
GOLDEN="${WINTEST_HOME:-$HOME/.cache/crosspad-wintest}/golden"
REPO="${WINRUNNER_REPO:-CrossPad/crosspad-hil}"
NAME="${WINRUNNER_NAME:-$(hostname)-win}"
LABEL=crosspad-win
# Windows' name for the host's zone (Europe/Warsaw): the VM's RTC is host local time.
WINTZ="${WINRUNNER_TZ:-Central European Standard Time}"
C=crosspad-winrunner
D() { docker --context default "$@"; }
run() {
  # --restart: the VM comes back with the machine; the runner service with Windows.
  D run -d --name $C --restart unless-stopped -e VERSION=11 -e RAM_SIZE=8G -e CPU_CORES=6 \
    -e DISK_SIZE=80G --device=/dev/kvm --device=/dev/net/tun --cap-add NET_ADMIN \
    -p 127.0.0.1:8007:8006 -v "$R/oem:/oem" -v "$W/shared:/shared" -v "$W/storage:/storage" \
    --stop-timeout 120 dockurr/windows >/dev/null
}
stop() { D stop -t 120 $C >/dev/null 2>&1 || true; D rm $C >/dev/null 2>&1 || true; }
case "$1" in
  create)
    [ -f "$GOLDEN/data.img" ] || { echo "no golden disk in $GOLDEN (wintest.sh golden)"; exit 2; }
    D inspect $C >/dev/null 2>&1 && { echo "$C exists; stop it first (winrunner.sh stop)"; exit 2; }
    mkdir -p "$W/shared" && chmod 700 "$W/shared"
    rm -rf "$W/storage"; mkdir -p "$W/storage"
    for f in "$GOLDEN"/*; do cp --sparse=always "$f" "$W/storage/"; done
    rm -f "$W/shared/ready.txt" "$W/shared/setup.log" "$W/shared/finished" "$W/shared/run-test.started.ps1"
    # Short-lived (1 h) and good for one registration only; the VM deletes the
    # file before it uses it.
    gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq .token > "$W/shared/token.txt"
    printf 'REPO=%s\nNAME=%s\nLABEL=%s\nTZ=%s\n' "$REPO" "$NAME" "$LABEL" "$WINTZ" > "$W/shared/runner.cfg"
    cp "$R/jobs/runner-setup.ps1" "$W/shared/run-test.ps1"
    run
    echo "VM booting; Git + runner setup in it (~5 min)…"
    until [ -e "$W/shared/finished" ]; do sleep 10; done
    rm -f "$W/shared/token.txt"
    cat "$W/shared/setup.log"
    "$0" status ;;
  start)
    # wintest.sh's job queue at logon, so winrunner.sh job reaches the VM
    stop; rm -f "$W/shared/job.ps1" "$W/shared/job-running.ps1" "$W/shared/job.done"
    cp "$R/jobs/queue.ps1" "$W/shared/run-test.ps1"
    run; echo "started; the runner comes online once Windows is up (~1 min)" ;;
  stop) stop ;;
  job)
    until [ ! -e "$W/shared/job.ps1" ] && [ ! -e "$W/shared/job-running.ps1" ]; do sleep 3; done
    rm -f "$W/shared/job.out" "$W/shared/job.done"; cp "$2" "$W/shared/job.ps1"
    until [ -e "$W/shared/job.done" ]; do sleep 3; done
    iconv -f utf-16 -t utf-8 "$W/shared/job.out" 2>/dev/null || cat "$W/shared/job.out" ;;
  on)  gh variable set CI_WIN_RUNNER -R "$REPO" --body "$LABEL" ;;
  off) gh variable delete CI_WIN_RUNNER -R "$REPO" 2>/dev/null || true ;;
  status)
    echo -n "VM: "; D inspect -f '{{.State.Status}}' $C 2>/dev/null || echo "absent"
    echo -n "runner: "; gh api "repos/$REPO/actions/runners" \
      --jq ".runners[] | select(.name==\"$NAME\") | \"\(.name) \(.status) busy=\(.busy)\"" | grep . || echo "not registered"
    echo -n "CI_WIN_RUNNER: "; gh variable list -R "$REPO" | awk '$1=="CI_WIN_RUNNER"{print $2}' | grep . || echo "unset (windows-latest)" ;;
  *) sed -n 2,18p "$0"; exit 2 ;;
esac
