"""Overpass client tests (no network: requests.post is monkeypatched)."""

import json

import pytest

from restspots import overpass
from restspots.config import get_country


class _FakeResp:
    def __init__(self, payload):
        self.text = json.dumps(payload)
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_build_query_uses_area_override():
    q = overpass.build_query(get_country("DE"), area='["ISO3166-2"="DE-SL"]')
    assert '["ISO3166-2"="DE-SL"]' in q
    assert "leisure" in q and "playground" in q


def test_run_overpass_raises_on_timeout_remark(tmp_path, monkeypatch):
    payload = {"elements": [], "remark": 'runtime error: Query timed out in "query" after 180 s'}
    monkeypatch.setattr(overpass.requests, "post", lambda *a, **k: _FakeResp(payload))
    with pytest.raises(RuntimeError, match="Overpass query failed"):
        overpass.run_overpass("[out:json];", "XX", raw_dir=tmp_path)
    # A failed query must NOT be cached (so a retry can run).
    assert not list(tmp_path.glob("osm_XX_*.json"))


def test_run_overpass_caches_success(tmp_path, monkeypatch):
    payload = {"elements": [{"type": "node", "id": 1, "tags": {}}]}
    monkeypatch.setattr(overpass.requests, "post", lambda *a, **k: _FakeResp(payload))
    data = overpass.run_overpass("[out:json];", "XX", raw_dir=tmp_path)
    assert len(data["elements"]) == 1
    assert len(list(tmp_path.glob("osm_XX_*.json"))) == 1
