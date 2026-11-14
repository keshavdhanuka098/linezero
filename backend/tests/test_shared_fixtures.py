import json
from pathlib import Path

import pytest

from app.engines.queueing_theory import mmc

FIXTURES = json.loads((Path(__file__).resolve().parents[2] / "shared" / "queueing_fixtures.json").read_text())["cases"]


@pytest.mark.parametrize("case", FIXTURES)
def test_mmc_matches_shared_fixture(case):
    r = mmc(case["lambda"], case["mu"], case["servers"])
    if case.get("stable") is False:
        assert r["stable"] is False
        return
    assert r["probability_of_wait"] == pytest.approx(case["p_wait"], rel=1e-9)
    assert r["avg_waiting_time"] == pytest.approx(case["wq"], rel=1e-9)
    assert r["avg_queue_length"] == pytest.approx(case["lq"], rel=1e-9)
