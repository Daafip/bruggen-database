import datetime as dt

import geopandas as gpd
import pytest
from shapely.geometry import Point

from restspots.export import MYMAPS_ROW_LIMIT, write_all, write_csv_wkt


def _gold():
    df = gpd.GeoDataFrame(
        {
            "id": ["node/1", "way/2"],
            "name": ["Stop One", "Stop Two"],
            "lat": [52.2, 51.0],
            "lon": [6.0, 7.0],
            "feature_type": ["rest_area", "services"],
            "motorway_ref": ["A7", None],
            "playground_count": [1, 3],
            "match_type": ["proximity", "contained"],
            "osm_url": [
                "https://www.openstreetmap.org/node/1",
                "https://www.openstreetmap.org/way/2",
            ],
            "data_retrieved_at": [dt.date(2026, 6, 22), dt.date(2026, 6, 22)],
        },
        geometry=[Point(6.0, 52.2), Point(7.0, 51.0)],
        crs=4326,
    )
    return df


def test_write_all_creates_three_formats(tmp_path):
    gdf = _gold()
    df = gdf.drop(columns="geometry")
    paths = write_all(gdf, df, tmp_path, "DE")
    assert set(paths) == {"geojson", "kml", "csv"}
    for p in paths.values():
        assert p.exists() and p.stat().st_size > 0
    # GeoJSON must be readable back as features.
    back = gpd.read_file(paths["geojson"])
    assert len(back) == 2


def test_csv_has_wkt_column(tmp_path):
    df = _gold().drop(columns="geometry")
    out = tmp_path / "out.csv"
    write_csv_wkt(df, out)
    header = out.read_text().splitlines()[0]
    assert "WKT" in header
    assert "latitude" in header and "longitude" in header


def test_csv_row_limit_raises(tmp_path):
    df = _gold().drop(columns="geometry")
    big = df.loc[df.index.repeat(MYMAPS_ROW_LIMIT)].reset_index(drop=True)
    with pytest.raises(ValueError, match="row layer limit"):
        write_csv_wkt(big, tmp_path / "big.csv")
