"""Normalize OSM bridges from either extract path into a single GeoDataFrame shape.

Both paths yield a GeoDataFrame with columns ``[tags, type, id, geometry]`` plus a
``feature_kind`` (``carriageway`` / ``structure``), so everything downstream is
source-agnostic — exactly as the rest-stops pipeline keeps Overpass and ``.pbf`` output
interchangeable.
"""

from __future__ import annotations

import geopandas as gpd

from . import osm
from .config import BridgeConfig

# Recognised values of the OSM ``bridge=*`` tag (everything except ``no``).
BRIDGE_VALUES = {
    "yes",
    "viaduct",
    "aqueduct",
    "boardwalk",
    "cantilever",
    "movable",
    "trestle",
    "covered",
    "low_water_crossing",
    "simple_brunnel",
}


def _tag(tags, key: str):
    return tags.get(key) if isinstance(tags, dict) else None


def classify(tags) -> str | None:
    """Return ``carriageway`` / ``structure`` / ``None`` for a feature's tags.

    A way carrying a real ``bridge=*`` tag is the *carriageway* on the bridge (it holds the
    functional tags); a ``man_made=bridge`` feature with no bridge tag is the *structure*
    outline.
    """
    bridge = _tag(tags, "bridge")
    if bridge is not None and bridge != "no":
        return "carriageway"
    if _tag(tags, "man_made") == "bridge":
        return "structure"
    return None


def from_overpass(overpass_json: dict) -> gpd.GeoDataFrame:
    """Path A: Overpass JSON -> classified bridge GeoDataFrame."""
    gdf = osm.to_gdf(overpass_json)
    if not len(gdf):
        gdf["feature_kind"] = []
        return gdf
    kind = gdf["tags"].apply(classify)
    gdf = gdf[kind.notna()].copy()
    gdf["feature_kind"] = kind[kind.notna()].values
    return gdf


def from_pbf(pbf_path, cfg: BridgeConfig) -> gpd.GeoDataFrame:  # noqa: ARG001
    """Path B: stream a ``.pbf`` and return the classified bridge GeoDataFrame.

    Filters on the ``bridge`` and ``man_made`` keys in C++ so only bridge features reach
    Python; relations are skipped (D2 in DECISIONS.md — negligible omission, avoids
    multipolygon assembly).
    """
    import osmium
    from shapely.geometry import Point

    rows: list[dict] = []
    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("bridge", "man_made"))
    )
    for obj in fp:
        tags = dict(obj.tags)
        kind = classify(tags)
        if kind is None:
            continue
        if obj.is_way():
            geom = osm.way_geometry(obj)
            otype = "way"
        elif obj.is_node():
            geom = Point(obj.location.lon, obj.location.lat)
            otype = "node"
        else:
            continue  # relations skipped
        if geom is None:
            continue
        rows.append(
            {"tags": tags, "type": otype, "id": obj.id, "geometry": geom, "feature_kind": kind}
        )

    if not rows:
        return gpd.GeoDataFrame(
            {"tags": [], "type": [], "id": [], "feature_kind": []},
            geometry=[],
            crs=4326,
        )
    geoms = [r.pop("geometry") for r in rows]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)
