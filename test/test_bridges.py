"""Network-free tests for the bridge pipeline (Part B).

Synthetic geometries + tags exercise classification, the canonical schema, length/numeric
parsing, and validation — no Overpass / .pbf access.
"""

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from bridges import schema, validate
from bridges.config import get_country
from bridges.extract import classify
from bridges.query import build_query


# --------------------------------------------------------------------------- config
def test_nl_config_uses_rd_new():
    cfg = get_country("NL")
    assert cfg.iso == "NL"
    assert cfg.proj_crs == 28992  # Amersfoort / RD New


# ---------------------------------------------------------------------------- query
def test_build_query_country_and_bbox():
    cfg = get_country("NL")
    q = build_query(cfg)
    assert 'area["ISO3166-1"="NL"]' in q
    assert 'way["bridge"]["bridge"!="no"]' in q
    assert 'way["man_made"="bridge"]' in q

    qb = build_query(cfg, bbox=(52.0, 4.3, 52.1, 4.5))
    assert "(52.0,4.3,52.1,4.5)" in qb
    assert "area" not in qb  # bbox scope replaces the area selector


# ------------------------------------------------------------------------ classify
def test_classify():
    assert classify({"bridge": "yes", "highway": "primary"}) == "carriageway"
    assert classify({"bridge": "movable"}) == "carriageway"
    assert classify({"man_made": "bridge"}) == "structure"
    assert classify({"bridge": "no"}) is None
    assert classify({"highway": "primary"}) is None
    assert classify(None) is None


def test_from_overpass_filters_and_labels():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "type": "way",
                    "id": 1,
                    "tags": {"bridge": "yes", "highway": "primary"},
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[4.0, 52.0], [4.001, 52.0]],
                },
            },
            {
                "type": "Feature",
                "properties": {"type": "way", "id": 2, "tags": {"highway": "primary"}},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[4.0, 52.0], [4.001, 52.0]],
                },
            },
        ],
    }
    # from_overpass goes via osm2geojson in the real path; here feed a GeoDataFrame-shaped
    # FeatureCollection through to_gdf indirectly is awkward, so test classify+schema below.
    # (Integration of to_gdf is covered by the live bbox run in the pipeline.)
    assert classify(fc["features"][0]["properties"]["tags"]) == "carriageway"
    assert classify(fc["features"][1]["properties"]["tags"]) is None


# -------------------------------------------------------------------------- schema
def _bridge_gdf():
    return gpd.GeoDataFrame(
        {
            "tags": [
                {
                    "bridge": "movable",
                    "bridge:movable": "bascule",
                    "highway": "secondary",
                    "name": "Testbrug",
                    "ref": "N206",
                    "width": "8 m",
                    "maxheight": "4.2",
                    "maxweight": "30 t",
                    "layer": "1",
                    "start_date": "1932",
                },
                {"man_made": "bridge", "bridge:structure": "arch"},
                {"bridge": "aqueduct", "waterway": "canal"},
            ],
            "type": ["way", "way", "way"],
            "id": [101, 102, 103],
            "feature_kind": ["carriageway", "structure", "carriageway"],
        },
        geometry=[
            LineString([(4.48, 52.16), (4.4808, 52.16)]),  # ~55 m E-W
            Polygon(
                [(4.49, 52.16), (4.4902, 52.16), (4.4902, 52.1602), (4.49, 52.1602)]
            ),
            LineString([(4.50, 52.16), (4.5005, 52.16)]),
        ],
        crs=4326,
    )


def test_to_canonical_fields():
    df = schema.to_canonical(_bridge_gdf(), "NL", proj_crs=28992)
    assert len(df) == 3
    movable = df[df["id"] == "way/101"].iloc[0]
    assert movable["name"] == "Testbrug"
    assert movable["is_movable"]
    assert movable["movable"] == "bascule"
    assert movable["carries_type"] == "road"
    assert movable["ref"] == "N206"
    assert movable["width_m"] == 8.0
    assert movable["maxheight_m"] == 4.2
    assert movable["maxweight_t"] == 30.0
    assert movable["layer"] == 1
    assert movable["length_m"] and movable["length_m"] > 40  # RD-New metres

    structure = df[df["id"] == "way/102"].iloc[0]
    assert structure["feature_kind"] == "structure"
    assert structure["bridge_type"] == "structure"
    assert structure["structure"] == "arch"
    import pandas as pd

    assert pd.isna(structure["length_m"])  # polygon: no span length

    aqueduct = df[df["id"] == "way/103"].iloc[0]
    assert aqueduct["bridge_type"] == "aqueduct"
    assert aqueduct["carries_type"] == "water"


def test_to_canonical_empty():
    empty = gpd.GeoDataFrame(
        {"tags": [], "type": [], "id": [], "feature_kind": []}, geometry=[], crs=4326
    )
    df = schema.to_canonical(empty, "NL", proj_crs=28992)
    assert list(df.columns) == schema.CANONICAL_FIELDS
    assert len(df) == 0


# -------------------------------------------------------------------------- viewer
def test_build_viewer(tmp_path):
    from bridges.viewer import build_viewer

    csv = tmp_path / "bridges_NL.csv"
    pd_df = schema.to_canonical(_bridge_gdf(), "NL", proj_crs=28992)
    pd_df.to_csv(csv, index=False)

    out = build_viewer(csv, tmp_path / "viewer.html", country="NL")
    assert out.exists()
    html = out.read_text()
    assert "leaflet" in html.lower()
    assert "Bridges of NL" in html  # legend title
    assert "Movable bridges (1)" in html  # one movable bridge in the fixture
    assert "bascule" in html


# ------------------------------------------------------------------------ validate
def test_validate_report():
    gdf = _bridge_gdf()
    df = schema.to_canonical(gdf, "NL", proj_crs=28992)
    geo = schema.attach_geometry(df, gdf)
    report = validate.validate(geo, df, "NL")
    assert report["passed"]
    assert report["total_bridges"] == 3
    assert report["movable_bridges"] == 1
    assert report["by_feature_kind"]["carriageway"] == 2
    assert report["by_carries_type"]["water"] == 1
