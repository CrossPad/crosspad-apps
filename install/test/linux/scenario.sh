#!/bin/bash
# Runs inside ubuntu:24.04. /inst holds install.sh under test and receives the logs.
apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo curl ca-certificates >/dev/null
useradd -m -s /bin/bash musician && echo 'musician ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/musician
cp /inst/install.sh /home/musician/install.sh && chown musician /home/musician/install.sh
run() { su - musician -c "GH_TOKEN=$GH_TOKEN CROSSPAD_YES=1 CROSSPAD_NO_TUI=1 $2 USER=musician bash ~/install.sh" > /inst/$1.log 2>&1; echo "exit=$?" >> /inst/$1.log; }
run 1-fresh "CROSSPAD_WITH_PC=1 CROSSPAD_WITH_ARDUINO=1"
# Broken: no Python env, a component without its .git, ESP-IDF's tools/ gone.
su - musician -c 'rm -rf ~/.espressif/python_env; rm -f ~/CrossPad/components/crosspad-sampler/.git; mv ~/esp/esp-idf/tools ~/esp/esp-idf/tools.gone'
run 2-broken ""
# Someone who had ESP-IDF 5.5 from EIM before: it is found, used, not cloned again.
su - musician -c 'mkdir -p ~/esp/v5.5.5 && mv ~/esp/esp-idf ~/esp/v5.5.5/esp-idf && rm -f ~/esp/v5.5.5/esp-idf/.crosspad-installed && printf "{\"idfToolsPath\": \"%s/.espressif\", \"idfInstalled\": {\"x\": {\"version\": \"5.5.5\", \"path\": \"%s/esp/v5.5.5/esp-idf\"}}, \"idfSelectedId\": \"x\"}\n" $HOME $HOME > ~/.espressif/esp_idf.json'
run 3-existing-idf ""
# Their ESP-IDF named by CROSSPAD_IDF_DIR, with an edit of theirs and a broken idf.py:
# the installer must not `git checkout -- .` over it.
su - musician -c 'echo "# mine" >> ~/esp/v5.5.5/esp-idf/README.md; rm -rf ~/.espressif/python_env'
run 4-foreign-idf-dir "CROSSPAD_IDF_DIR=/home/musician/esp/v5.5.5/esp-idf"
su - musician -c 'tail -1 ~/esp/v5.5.5/esp-idf/README.md' > /inst/4-foreign-edit.txt 2>&1
su - musician -c "ls -d ~/esp/*; for c in cptools crosspad-flash crosspad-files crosspad-bench crosspad-board crosspad-idf crosspad-hil crosspad-sim crosspad-pc crosspad-arduino pio; do bash -lc \"command -v \$c\" || echo \"MISSING \$c\"; done; bash -lc 'crosspad-hil --version; crosspad-board --help | head -2; cd /tmp && crosspad-idf board; ls -d /tmp/build_v2 2>/dev/null && echo STRAY-BUILD-DIR'; GH_TOKEN=$GH_TOKEN bash -lc 'cptools doctor'; echo doctor exit=\$?" > /inst/5-commands.log 2>&1
chown -R --reference=/inst /inst
echo done > /inst/finished
