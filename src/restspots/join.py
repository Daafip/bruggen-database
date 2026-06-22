"""Phase 2/3 — normalize Overpass JSON, spatially join playgrounds, attach enrichment.

Project CRS is **EPSG:3035** (LAEA Europe, equal-area) so multi-country merges stay
consistent. A rest stop qualifies via one of three rules, recorded in ``match_type``:

* ``tag``        — the stop itself carries ``playground=yes`` (authoritative, rare)
* ``contained``  — a playground falls inside the stop polygon (areas only)
* ``proximity``  — a playground lies within a buffer of a point-mapped stop (common)
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from osm2geojson import json2geojson

PROJ = 3035  # pan-European equal-area metric CRS
STOP_HIGHWAY = {"services", "rest_area"}


def to_gdf(overpass_json: dict) -> gpd.GeoDataFrame:
    """Convert raw Overpass JSON to a WGS84 GeoDataFrame (tags under the ``tags`` column)."""
    fc = json2geojson(overpass_json)
    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    if "tags" not in gdf.columns:
        gdf["tags"] = [{} for _ in range(len(gdf))]
    return gdf


def _tag(tags, key: str):
    return tags.get(key) if isinstance(tags, dict) else None


def split_features(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Split a combined extract into (rest stops, playgrounds) by their tags."""
    is_play = gdf["tags"].apply(lambda t: _tag(t, "leisure") == "playground")
    is_rest = gdf["tags"].apply(lambda t: _tag(t, "highway") in STOP_HIGHWAY)
    return gdf[is_rest].copy(), gdf[is_play].copy()


def attach_playgrounds(
    rest: gpd.GeoDataFrame,
    play: gpd.GeoDataFrame,
    contained_buf: float = 50.0,
    proximity_buf: float = 200.0,
) -> gpd.GeoDataFrame:
    """Flag rest stops that have a playground; keep only those, in WGS84.

    Adds ``playground_count``, ``has_playground`` and ``match_type``. Area-mapped stops
    get a small edge buffer (``contained``); point/line stops get a larger one
    (``proximity``) — the distinction is preserved in ``match_type`` for later QA.
    """
    rest_m = rest.to_crs(PROJ).copy()
    rest_m = rest_m.reset_index(drop=True)

    is_poly = rest_m.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    buf_dist = [
        contained_buf if p else proximity_buf for p in is_poly
    ]  # per-row distance
    zone_geom = rest_m.geometry.buffer(buf_dist)
    zones = gpd.GeoDataFrame({"_rid": rest_m.index}, geometry=zone_geom, crs=PROJ)

    if len(play):
        play_pts = play.to_crs(PROJ).copy()
        play_pts["geometry"] = play_pts.geometry.centroid  # point-in-zone test
        hits = gpd.sjoin(play_pts, zones, predicate="within", how="inner")
        counts = hits.groupby("_rid").size()
    else:
        counts = pd.Series(dtype="int64")

    rest_m["playground_count"] = counts.reindex(rest_m.index).fillna(0).astype(int)
    tagged = rest_m["tags"].apply(lambda t: _tag(t, "playground") == "yes")
    rest_m["has_playground"] = (rest_m["playground_count"] > 0) | tagged

    has_count = rest_m["playground_count"] > 0
    match_type = pd.Series(pd.NA, index=rest_m.index, dtype="object")
    match_type[has_count & ~is_poly] = "proximity"
    match_type[has_count & is_poly] = "contained"
    match_type[tagged] = "tag"  # authoritative tag wins
    rest_m["match_type"] = match_type

    kept = rest_m[rest_m["has_playground"]].copy()
    return kept.to_crs(4326)


def attach_nearest(
    gdf: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    fields: list[str],
    max_distance: float = 300.0,
    suffix: str = "",
) -> gpd.GeoDataFrame:
    """Attach the named fields from the nearest ``points`` feature within ``max_distance``.

    Used both to attach a motorway ``ref`` (nearest ``highway=motorway`` way,
    country-agnostic) and an official name/ref from a national connector (e.g. Autobahn).
    Operates in EPSG:3035 so ``max_distance`` is in metres.
    """
    if points is None or len(points) == 0:
        for f in fields:
            gdf[f"{f}{suffix}"] = pd.NA
        return gdf

    left = gdf.to_crs(PROJ).copy()
    right = points.to_crs(PROJ)[fields + ["geometry"]].copy()
    joined = gpd.sjoin_nearest(
        left, right, how="left", max_distance=max_distance, distance_col="_dist"
    )
    # sjoin_nearest can duplicate rows on ties; keep the first (closest) per original row.
    joined = joined[~joined.index.duplicated(keep="first")]
    for f in fields:
        gdf[f"{f}{suffix}"] = joined[f].values
    return gdf
