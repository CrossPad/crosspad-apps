import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))




import pytest


@pytest.fixture(autouse=True)
def _no_bench_holder(monkeypatch):
    """A bench machine names its sessions; the tests expect CP Tools' own name."""
    monkeypatch.delenv("CROSSPAD_BENCH_HOLDER", raising=False)
