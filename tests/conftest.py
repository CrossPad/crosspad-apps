import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _no_bench_holder(monkeypatch):
    """A bench machine names its sessions; the tests expect CP Tools' own name."""
    monkeypatch.delenv("CROSSPAD_BENCH_HOLDER", raising=False)


@pytest.fixture(autouse=True)
def _no_real_board(monkeypatch, tmp_path_factory):
    """A real CrossPad and ST-Link sit on the bench machine: a test that forgets its fake
    must find no crosspad-hil and no crosspad-trace, not the board. Tests that need one
    set CROSSPAD_HIL / CROSSPAD_TRACE themselves."""
    nowhere = str(tmp_path_factory.getbasetemp() / "not-installed")
    monkeypatch.setenv("CROSSPAD_HIL", nowhere)
    monkeypatch.setenv("CROSSPAD_TRACE", nowhere)
