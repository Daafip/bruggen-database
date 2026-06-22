"""End-to-end pipeline test running fully offline (no network) on a synthetic snapshot.

Uses country NL (no enrichment connectors) so nothing hits an external API.
"""

import json
from types import SimpleNamespace

import geopandas as gpd

from restspots.pipeline import cmd_build, cmd_export, cmd_validate

# A services node in NL with a playground ~11 m away, plus an empty stop far off.
SYNTHETIC_OVERPASS = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 52.1000,
            "lon": 5.1000,
            "tags": {
                "highway": "services",
                "name": "Verzorgingsplaats Speeltuin",
                "toilets": "yes",
            },
        },
        {
            "type": "node",
            "id": 2,
            "lat": 52.1001,
            "lon": 5.1000,
            "tags": {"leisure": "playground"},
        },
        {
            "type": "node",
            "id": 3,
            "lat": 52.5000,
            "lon": 6.0000,
            "tags": {"highway": "rest_area", "name": "Leeg Plekje"},
        },
    ]
}


def _args(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "osm_NL_2026-06-22_deadbeef.json").write_text(json.dumps(SYNTHETIC_OVERPASS))
    return SimpleNamespace(
        country="NL",
        config=None,
        raw_dir=str(raw),
        interim_dir=str(tmp_path / "interim"),
        processed_dir=str(tmp_path / "processed"),
        endpoint="http://unused.invalid",
    )


def test_build_export_validate_offline(tmp_path):
    args = _args(tmp_path)

    assert cmd_build(args) == 0
    gold = tmp_path / "processed" / "rest_stops_playgrounds_NL.gold.geojson"
    assert gold.exists()
    gdf = gpd.read_file(gold)
    # Only the stop with a playground survives.
    assert len(gdf) == 1
    assert gdf.iloc[0]["name"] == "Verzorgingsplaats Speeltuin"
    assert gdf.iloc[0]["match_type"] == "proximity"
    assert bool(gdf.iloc[0]["toilets"]) is True

    # run_metadata records provenance.
    meta = json.loads((tmp_path / "processed" / "run_metadata_NL.json").read_text())
    assert meta["osm_snapshot_date"] == "2026-06-22"
    assert meta["rows"] == 1

    assert cmd_export(args) == 0
    for ext in ("geojson", "kml", "csv"):
        assert (tmp_path / "processed" / f"rest_stops_playgrounds_NL.{ext}").exists()

    assert cmd_validate(args) == 0
