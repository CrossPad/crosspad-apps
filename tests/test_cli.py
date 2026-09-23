"""The CLI as scripts and Windows logs see it."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = ("import sys, crosspad_app_manager as c; sys.argv = ['crosspad-apps'] + sys.argv[1:]; "
       "c.cli_main(c.PlatformConfig(platform='pc', lib_dir='src/apps'))")


def cli(tmp_path, *args, encoding=None):
    (tmp_path / "apps.json").write_text(json.dumps({"installed": {}}))
    (tmp_path / "app-registry.json").write_text(json.dumps({"version": 1, "apps": {}}))
    env = dict(os.environ, PYTHONPATH=ROOT)
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    return subprocess.run([sys.executable, "-c", RUN, *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, errors="replace", timeout=60)


def test_doctor_survives_an_ansi_code_page(tmp_path):
    # Windows writes redirected output in cp1252, which has no arrow.
    r = cli(tmp_path, "doctor", encoding="cp1252")
    assert "UnicodeEncodeError" not in r.stderr and r.returncode in (0, 1)
    assert "Tools" in r.stdout


def test_json_answers_carry_a_schema_version(tmp_path):
    r = cli(tmp_path, "status", "--json")
    data = json.loads(r.stdout)
    assert data["schema_version"] == 1 and data["apps"] == []
    r = cli(tmp_path, "list", "--json")
    assert json.loads(r.stdout)["command"] == "list"


def test_track_takes_the_words_the_screens_use(tmp_path):
    r = cli(tmp_path, "track", "sampler", "development", "--ref", "master")
    assert r.returncode == 0, r.stderr
    cfg = json.loads((tmp_path / "crosspad.config.json").read_text())
    assert cfg["apps"]["sampler"] == {"track": "branch", "ref": "master"}
