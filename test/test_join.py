import geopandas as gpd
from shapely.geometry import Point, Polygon

from restspots.join import attach_nearest, attach_playgrounds


def _square(cx, cy, half=0.0005):
    return Polygon(
        [
            (cx - half, cy - half),
            (cx + half, cy - half),
            (cx + half, cy + half),
            (cx - half, cy + half),
        ]
    )


def _rest_gdf():
    # 0: polygon stop with a playground inside (-> contained)
    # 1: point stop with a playground ~11 m away (-> proximity)
    # 2: point stop with no playground nearby (-> dropped)
    return gpd.GeoDataFrame(
        {
            "tags": [
                {"highway": "services", "name": "Area Poly"},
                {"highway": "rest_area", "name": "Rastplatz Punkt"},
                {"highway": "services", "name": "Leer"},
            ]
        },
        geometry=[_square(5.10, 52.10), Point(6.00, 52.20), Point(7.00, 52.30)],
        crs=4326,
    )


def _play_gdf():
    return gpd.GeoDataFrame(
        {"tags": [{"leisure": "playground"}, {"leisure": "playground"}]},
        geometry=[Point(5.10, 52.10), Point(6.0001, 52.20)],
        crs=4326,
    )


def test_attach_playgrounds_match_types():
    stops = attach_playgrounds(
        _rest_gdf(), _play_gdf(), contained_buf=50, proximity_buf=200
    )
    # Only the two stops with a playground survive.
    assert len(stops) == 2
    by_name = {t["name"]: mt for t, mt in zip(stops["tags"], stops["match_type"])}
    assert by_name["Area Poly"] == "contained"
    assert by_name["Rastplatz Punkt"] == "proximity"
    assert stops["has_playground"].all()
    assert (stops["playground_count"] >= 1).all()


def test_attach_playgrounds_tag_rule_wins():
    rest = gpd.GeoDataFrame(
        {"tags": [{"highway": "rest_area", "playground": "yes", "name": "Tagged"}]},
        geometry=[Point(8.0, 50.0)],
        crs=4326,
    )
    empty = gpd.GeoDataFrame({"tags": []}, geometry=[], crs=4326)
    stops = attach_playgrounds(rest, empty)
    assert len(stops) == 1
    assert stops.iloc[0]["match_type"] == "tag"
    assert stops.iloc[0]["has_playground"]


def test_attach_nearest_within_distance():
    stops = gpd.GeoDataFrame(
        {"tags": [{"highway": "services"}]}, geometry=[Point(6.0, 52.2)], crs=4326
    )
    official = gpd.GeoDataFrame(
        {"official_name": ["Offizieller Name"], "official_ref": ["A7"]},
        geometry=[Point(6.0001, 52.2)],
        crs=4326,
    )
    out = attach_nearest(
        stops, official, ["official_name", "official_ref"], max_distance=300
    )
    assert out.iloc[0]["official_ref"] == "A7"
    assert out.iloc[0]["official_name"] == "Offizieller Name"


def test_attach_nearest_empty_points():
    stops = gpd.GeoDataFrame(
        {"tags": [{"highway": "services"}]}, geometry=[Point(6.0, 52.2)], crs=4326
    )
    empty = gpd.GeoDataFrame(
        {"official_name": [], "official_ref": []}, geometry=[], crs=4326
    )
    out = attach_nearest(stops, empty, ["official_name", "official_ref"])
    assert "official_ref" in out.columns
