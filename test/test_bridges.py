"""Network-free tests for the bridge pipeline (Part B).

Synthetic geometries + tags exercise classification, the canonical schema, length/numeric
parsing, and validation — no Overpass / .pbf access.
"""

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from bridges import schema, validate
from bridges.config import get_country
from bridges.extract import classify
from bridges.group import assign_groups
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


# --------------------------------------------------------------------------- group
def _group_gdf():
    # A,B: two road segments ~7 m apart (same type → merge).
    # C: a footbridge ~10 m from A (cross-type → must NOT merge).
    # D: a road segment ~68 m away (too far → own group).
    return gpd.GeoDataFrame(
        {
            "id": ["way/1", "way/2", "way/3", "way/4"],
            "carries_type": ["road", "road", "foot", "road"],
        },
        geometry=[
            Point(4.90000, 52.0),
            Point(4.90010, 52.0),
            Point(4.90015, 52.0),
            Point(4.90100, 52.0),
        ],
        crs=4326,
    )


def test_assign_groups_same_type_merges_cross_type_does_not():
    out = assign_groups(_group_gdf(), distance_m=25, crs=28992, country="NL")
    gid = dict(zip(out["id"], out["group_id"]))
    size = dict(zip(out["id"], out["group_size"]))
    assert gid["way/1"] == gid["way/2"]  # close, same type → one bridge
    assert gid["way/3"] != gid["way/1"]  # footbridge beside the road → kept separate
    assert gid["way/4"] != gid["way/1"]  # too far → separate
    assert size["way/1"] == 2 and size["way/3"] == 1
    assert out["group_id"].nunique() == 3


def test_assign_groups_empty():
    empty = gpd.GeoDataFrame({"id": [], "carries_type": []}, geometry=[], crs=4326)
    out = assign_groups(empty, country="NL")
    assert "group_id" in out.columns and len(out) == 0


def test_assign_groups_water_rule_merges_divided_carriageways():
    # Two road carriageway spans ~40 m apart (beyond the 25 m base rule), both crossing the
    # same canal -> one physical bridge via the same-waterway rule.
    bridges = gpd.GeoDataFrame(
        {
            "id": ["way/1", "way/2"],
            "carries_type": ["road", "road"],
            "name": [None, None],
        },
        geometry=[
            LineString([(4.9000, 52.0), (4.9000, 52.0006)]),
            LineString([(4.9006, 52.0), (4.9006, 52.0006)]),  # ~40 m east
        ],
        crs=4326,
    )
    canal = gpd.GeoDataFrame(
        {"water_id": ["way/100"]},
        geometry=[LineString([(4.8990, 52.0003), (4.9020, 52.0003)])],
        crs=4326,
    )
    merged = assign_groups(
        bridges, waterways=canal, distance_m=25, water_distance_m=80, crs=28992
    )
    gid = dict(zip(merged["id"], merged["group_id"]))
    assert gid["way/1"] == gid["way/2"]  # same canal + same type → one bridge

    # Without the waterway link they stay apart (proves rule 2 is what merged them).
    separate = assign_groups(
        bridges, waterways=None, distance_m=25, water_distance_m=80
    )
    gid2 = dict(zip(separate["id"], separate["group_id"]))
    assert gid2["way/1"] != gid2["way/2"]


def test_assign_groups_name_rule_merges_across_types():
    # A road bridge and a cycle bridge ~20 m apart sharing a name (e.g. "Plantagebrug")
    # merge despite different carries_type.
    bridges = gpd.GeoDataFrame(
        {
            "id": ["way/1", "way/2"],
            "carries_type": ["road", "cycle"],
            "name": ["Plantagebrug", "Plantagebrug"],
        },
        geometry=[Point(4.900, 52.0), Point(4.900, 52.00018)],  # ~20 m apart
        crs=4326,
    )
    out = assign_groups(bridges, distance_m=25, name_distance_m=60, crs=28992)
    gid = dict(zip(out["id"], out["group_id"]))
    assert gid["way/1"] == gid["way/2"]  # same name + near → one, across carries_type


# -------------------------------------------------------------------------- viewer
def test_collapse_to_groups():
    from bridges.viewer import _collapse_to_groups

    df = pd.DataFrame(
        {
            "group_id": ["NL-000001", "NL-000001", "NL-000002"],
            "lat": [52.0, 52.0, 53.0],
            "lon": [4.0, 4.0, 5.0],
            "name": [None, "Brug X", None],
            "bridge_type": ["yes", "yes", "movable"],
            "carries": ["highway=primary", "highway=primary", None],
            "movable": [None, None, "bascule"],
            "osm_url": ["u1", "u2", "u3"],
            "is_movable": [False, False, True],
        }
    )
    out = _collapse_to_groups(df)
    assert len(out) == 2  # two physical bridges from three features
    g1 = out[out["group_id"] == "NL-000001"].iloc[0]
    assert g1["name"] == "Brug X"  # first non-blank name wins
    assert int(g1["n_features"]) == 2
    g2 = out[out["group_id"] == "NL-000002"].iloc[0]
    assert bool(g2["is_movable"])


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
    assert report["total_features"] == 3
    assert report["movable_bridges"] == 1
    assert report["by_feature_kind"]["carriageway"] == 2
    assert report["by_carries_type"]["water"] == 1
