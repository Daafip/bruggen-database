import datetime as dt

import geopandas as gpd
from shapely.geometry import Point

from restspots.schema import CANONICAL_FIELDS, attach_geometry, to_canonical


def _joined():
    return gpd.GeoDataFrame(
        {
            "tags": [
                {
                    "highway": "services",
                    "name": "B Area",
                    "toilets": "yes",
                    "fuel": "yes",
                },
                {"highway": "rest_area", "name": "A Area", "toilets": "no"},
            ],
            "type": ["way", "node"],
            "id": [222, 111],
            "has_playground": [True, True],
            "playground_count": [2, 1],
            "match_type": ["contained", "proximity"],
        },
        geometry=[Point(6.0, 52.2), Point(7.0, 51.0)],
        crs=4326,
    )


def test_to_canonical_fields_and_sorting():
    df = to_canonical(_joined(), "DE", retrieved_at=dt.date(2026, 6, 22))
    assert list(df.columns) == CANONICAL_FIELDS
    # Sorted by id: node/111 before way/222
    assert df.iloc[0]["id"] == "node/111"
    assert df.iloc[1]["id"] == "way/222"


def test_to_canonical_amenities_and_urls():
    df = to_canonical(_joined(), "DE", retrieved_at=dt.date(2026, 6, 22))
    bnode = df[df["id"] == "way/222"].iloc[0]
    assert bool(bnode["toilets"]) is True
    assert bool(bnode["fuel"]) is True
    assert bnode["feature_type"] == "services"
    assert bnode["osm_url"] == "https://www.openstreetmap.org/way/222"
    assert bnode["country"] == "DE"
    anode = df[df["id"] == "node/111"].iloc[0]
    assert bool(anode["toilets"]) is False


def test_attach_geometry_roundtrip():
    df = to_canonical(_joined(), "DE")
    gdf = attach_geometry(df, _joined())
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.geometry.notna().all()
    assert gdf.crs.to_epsg() == 4326
