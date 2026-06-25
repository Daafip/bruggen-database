"""Normalize OSM into the GeoDataFrames the pipeline needs.

Both extract paths return ``(bridges, waterways)``:

* **bridges** — columns ``[tags, type, id, geometry, feature_kind]`` (``feature_kind`` is
  ``carriageway`` / ``structure``), identical from Overpass or ``.pbf`` so everything
  downstream is source-agnostic.
* **waterways** — ``[water_id, geometry]`` for river/canal/stream centrelines, used by
  :mod:`bridges.group` to tell whether two bridges cross the *same* body of water (so the two
  carriageways of a divided road over one canal become a single bridge).
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

# "Bodies of water" a road crosses: linear waterways. Ditches/drains are excluded (tiny,
# numerous, not what "a road over the water" means).
WATERWAY_VALUES = {"river", "canal", "stream"}


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


def is_waterway(tags) -> bool:
    """True for a river/canal/stream centreline (a body of water a bridge can cross)."""
    return _tag(tags, "waterway") in WATERWAY_VALUES


def from_overpass(overpass_json: dict) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Path A: Overpass JSON -> ``(classified bridges, waterways)``."""
    gdf = osm.to_gdf(overpass_json)
    if not len(gdf):
        empty = gdf.copy()
        empty["feature_kind"] = []
        return empty, _waterways_gdf([])

    kind = gdf["tags"].apply(classify)
    bridges = gdf[kind.notna()].copy()
    bridges["feature_kind"] = kind[kind.notna()].to_numpy()

    is_w = gdf["tags"].apply(is_waterway) & kind.isna()
    water = gdf[is_w]
    rows = [
        {"water_id": f"{t}/{i}", "geometry": geom}
        for t, i, geom in zip(water["type"], water["id"], water.geometry)
        if geom is not None
    ]
    return bridges, _waterways_gdf(rows)


def from_pbf(pbf_path, cfg: BridgeConfig) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:  # noqa: ARG001
    """Path B: stream a ``.pbf`` and return ``(classified bridges, waterways)``.

    Filters on the ``bridge``, ``man_made`` and ``waterway`` keys in C++ so only relevant
    features reach Python; relations are skipped (D2 in DECISIONS.md — negligible omission,
    avoids multipolygon assembly).
    """
    import osmium
    from shapely.geometry import Point

    bridge_rows: list[dict] = []
    water_rows: list[dict] = []
    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("bridge", "man_made", "waterway"))
    )
    for obj in fp:
        tags = dict(obj.tags)
        kind = classify(tags)
        if kind is not None:
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
            bridge_rows.append(
                {
                    "tags": tags,
                    "type": otype,
                    "id": obj.id,
                    "geometry": geom,
                    "feature_kind": kind,
                }
            )
        elif is_waterway(tags) and obj.is_way():
            geom = osm.way_geometry(obj)
            if geom is not None:
                water_rows.append({"water_id": f"way/{obj.id}", "geometry": geom})

    return _bridges_gdf(bridge_rows), _waterways_gdf(water_rows)


def _bridges_gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    if not rows:
        return gpd.GeoDataFrame(
            {"tags": [], "type": [], "id": [], "feature_kind": []},
            geometry=[],
            crs=4326,
        )
    geoms = [r.pop("geometry") for r in rows]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)


def _waterways_gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    if not rows:
        return gpd.GeoDataFrame({"water_id": []}, geometry=[], crs=4326)
    geoms = [r["geometry"] for r in rows]
    return gpd.GeoDataFrame(
        {"water_id": [r["water_id"] for r in rows]}, geometry=geoms, crs=4326
    )
