#!/bin/bash
# Clean-Windows test bench for the CrossPad installer (dockurr/windows).
#   wintest.sh golden   first time: install Windows 11 once (downloads the ISO), keep the clean disk
#   wintest.sh golden-fl  the clean copy + FL Studio (trial), kept as golden-fl/
#   wintest.sh start [fl] start from the clean copy (or the FL one), runner waits for run-test.ps1
#   wintest.sh fl         FL Studio integration with the board passed through: install
#                         CrossPad, then jobs/fl-check.ps1 (needs shared/token.txt)
#   wintest.sh resume     start the disk as it was left (WINTEST_USB=1 for the board)
#   wintest.sh stop
#   wintest.sh job FILE.ps1  run FILE in the VM, wait, print its output
# At logon the VM starts jobs/queue.ps1, which runs each shared/job.ps1 —
# nothing is ever typed into the Run dialog (Defender: ClickFix).
# Scripts come from this folder; the disks, the ISO and the share live in
# $WINTEST_HOME (default ~/.cache/crosspad-wintest): ~11 GB clean disk, ~16 GB
# with FL, up to ~40 GB for the running disk after a full setup.
set -e
R="$(cd "$(dirname "$0")" && pwd)"
W="${WINTEST_HOME:-$HOME/.cache/crosspad-wintest}"
mkdir -p "$W/shared" "$W/storage" "$W/iso"
run() {
  local iso=() usb=()
  # A sound card (silent on the host side): FL Studio's settings window hangs
  # for good on a machine without an audio endpoint, and no user has one.
  local qemu="-audiodev none,id=snd0 -device ich9-intel-hda -device hda-duplex,audiodev=snd0"
  [ -f "$W/iso/win11x64.iso" ] && iso=(-v "$W/iso/win11x64.iso:/custom.iso:ro")
  # WINTEST_USB=1: the CrossPad (ESP 303a:3456, STM bridge 0483:5740) moves into
  # the VM — the host loses it until the VM stops.
  # The bus is mounted live (not --device, which copies the nodes present at
  # start): a board that restarts comes back under a new address, and
  # follow_usb hands the new one to the VM.
  if [ -n "${WINTEST_USB:-}" ]; then
    usb=(-v /dev/bus/usb:/dev/bus/usb --device-cgroup-rule "c 189:* rmw")
    qemu="$qemu -device usb-host,id=esp,vendorid=0x303a,productid=0x3456 -device usb-host,id=stm,vendorid=0x0483,productid=0x5740"
  fi
  docker --context default run -d --name crosspad-wintest -e VERSION=11 -e RAM_SIZE=8G -e CPU_CORES=6 \
    -e DISK_SIZE=80G --device=/dev/kvm --device=/dev/net/tun --cap-add NET_ADMIN -p 8006:8006 \
    -v "$R/oem:/oem" -v "$W/shared:/shared" -v "$W/storage:/storage" "${iso[@]}" "${usb[@]}" -e "ARGUMENTS=$qemu" \
    --stop-timeout 120 dockurr/windows >/dev/null
}
# libusb inside the container gets no hotplug events, so QEMU never sees a
# board that comes back under a new address (a restart after a flash): re-add
# that device by its node, which QEMU opens without enumerating.
follow_usb() {
  echo $$ > "$W/follow_usb.pid"
  declare -A last
  while docker --context default inspect -f '{{.State.Running}}' crosspad-wintest 2>/dev/null | grep -q true; do
    for d in esp:303a:3456 stm:0483:5740; do
      id=${d%%:*}; vp=${d#*:}
      cur=$(lsusb -d "$vp" 2>/dev/null | awk '{sub(":", "", $4); print "/dev/bus/usb/" $2 "/" $4}' | head -1)
      case "$cur" in */000) cur="" ;; esac   # mid-enumeration: no address yet
      if [ -n "$cur" ] && [ -n "${last[$id]:-}" ] && [ "$cur" != "${last[$id]}" ]; then
        sleep 1
        docker --context default exec crosspad-wintest python3 -c '
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect("/run/shm/monitor.sock")
for cmd in ("device_del " + sys.argv[1], "device_add usb-host,id=%s,hostdevice=%s" % (sys.argv[1], sys.argv[2])):
    s.sendall((cmd + "\n").encode()); time.sleep(1.5)
' "$id" "$cur" >/dev/null 2>&1
        echo "$(date +%T) $id moved to $cur, re-added" >> "$W/follow_usb.log"
      fi
      [ -n "$cur" ] && last[$id]=$cur
    done
    sleep 1
  done
}
stop() { [ -f "$W/follow_usb.pid" ] && kill "$(cat "$W/follow_usb.pid")" 2>/dev/null; rm -f "$W/follow_usb.pid"
         docker --context default stop -t 120 crosspad-wintest >/dev/null 2>&1 || true
         docker --context default rm crosspad-wintest >/dev/null 2>&1 || true; }
case "$1" in
  golden)
    stop; rm -f "$W/shared/ready.txt"; run
    echo "installing Windows; waiting for the first logon…"
    until [ -e "$W/shared/ready.txt" ]; do sleep 20; done
    stop
    [ -f "$W/storage/win11x64.iso" ] && mv "$W/storage/win11x64.iso" "$W/iso/"
    rm -rf "$W/golden"; mkdir -p "$W/golden"
    for f in "$W"/storage/*; do [ -f "$f" ] && cp --sparse=always "$f" "$W/golden/"; done
    echo "golden copy: $(du -sh "$W/golden" | cut -f1)" ;;
  start)
    src="$W/golden"; [ "$2" = "fl" ] && src="$W/golden-fl"
    stop; rm -f "$W/shared/ready.txt"
    rm -f "$W/shared/job.ps1" "$W/shared/job-running.ps1" "$W/shared/job.done"; cp "$R/jobs/queue.ps1" "$W/shared/run-test.ps1"
    rm -rf "$W/storage"; mkdir -p "$W/storage"
    for f in "$src"/*; do cp --sparse=always "$f" "$W/storage/"; done
    run
    if [ -n "${WINTEST_USB:-}" ]; then
      setsid nohup "$0" follow-usb >/dev/null 2>&1 < /dev/null &
    fi
    until [ -e "$W/shared/ready.txt" ]; do sleep 5; done; echo "ready" ;;
  golden-fl)
    "$0" start
    rm -f "$W/shared/finished" "$W/shared/fl-install.log"
    cp "$R/jobs/fl-install.ps1" "$W/shared/job.ps1"
    echo "installing FL Studio…"
    until [ -e "$W/shared/finished" ]; do sleep 20; done
    cat "$W/shared/fl-install.log"
    stop
    rm -rf "$W/golden-fl"; mkdir -p "$W/golden-fl"
    for f in "$W"/storage/*; do [ -f "$f" ] && cp --sparse=always "$f" "$W/golden-fl/"; done
    echo "golden-fl: $(du -sh "$W/golden-fl" | cut -f1)" ;;
  fl)
    [ -f "$W/shared/token.txt" ] || { echo "shared/token.txt (a GitHub token) is missing"; exit 2; }
    WINTEST_USB=1 "$0" start fl
    rm -f "$W/shared/finished" "$W/shared/fl-test.log"
    cp "$R/jobs/fl-check.ps1" "$W/shared/"
    cp "$R/jobs/run-fl.ps1" "$W/shared/job.ps1"
    echo "installing CrossPad, then FL checks…"
    until [ -e "$W/shared/finished" ]; do sleep 20; done
    iconv -f utf-16 -t utf-8 "$W/shared/fl-test.log" | grep -E '^(PASS|FAIL|RESULT)'
    iconv -f utf-16 -t utf-8 "$W/shared/fl-test.log" | grep -q '^RESULT: PASS' ;;
  job)
    until [ ! -e "$W/shared/job.ps1" ] && [ ! -e "$W/shared/job-running.ps1" ]; do sleep 3; done
    rm -f "$W/shared/job.out" "$W/shared/job.done"; cp "$2" "$W/shared/job.ps1"
    until [ -e "$W/shared/job.done" ]; do sleep 3; done
    iconv -f utf-16 -t utf-8 "$W/shared/job.out" 2>/dev/null || cat "$W/shared/job.out" ;;
  resume)
    # the disk as it was left (no golden copy), e.g. after freeing the board
    stop; rm -f "$W/shared/ready.txt"; cp "$R/jobs/queue.ps1" "$W/shared/run-test.ps1"
    run
    if [ -n "${WINTEST_USB:-}" ]; then
      setsid nohup "$0" follow-usb >/dev/null 2>&1 < /dev/null &
    fi
    until [ -e "$W/shared/ready.txt" ]; do sleep 5; done; echo "ready" ;;
  follow-usb) follow_usb ;;
  stop) stop ;;
  *) sed -n 2,15p "$0"; exit 2 ;;
esac
