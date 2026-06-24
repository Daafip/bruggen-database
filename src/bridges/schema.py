"""Canonical bridge schema. The internal model never changes; only the serializer differs
per output format (see :mod:`bridges.export`).

A bridge IS the feature, so — unlike the rest-stops pipeline — this is a straight
tag→record mapping with no spatial join. ``length_m`` is the one geometry-derived field
(computed in the configured metric CRS).
"""

from __future__ import annotations

import datetime as dt
import re

import geopandas as gpd
import pandas as pd
from pydantic import BaseModel

CANONICAL_FIELDS = [
    "id",
    "name",
    "country",
    "lat",
    "lon",
    "feature_kind",
    "bridge_type",
    "structure",
    "movable",
    "is_movable",
    "carries",
    "carries_type",
    "ref",
    "layer",
    "length_m",
    "width_m",
    "maxweight_t",
    "maxheight_m",
    "material",
    "operator",
    "start_date",
    "source",
    "osm_url",
    "data_retrieved_at",
]

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


class Bridge(BaseModel):
    """One OSM bridge — the canonical record."""

    id: str
    name: str | None = None
    country: str
    lat: float
    lon: float
    feature_kind: str
    bridge_type: str | None = None
    structure: str | None = None
    movable: str | None = None
    is_movable: bool = False
    carries: str | None = None
    carries_type: str | None = None
    ref: str | None = None
    layer: int | None = None
    length_m: float | None = None
    width_m: float | None = None
    maxweight_t: float | None = None
    maxheight_m: float | None = None
    material: str | None = None
    operator: str | None = None
    start_date: str | None = None
    source: str = "osm"
    osm_url: str | None = None
    data_retrieved_at: dt.date | None = None


def _tag(tags, key: str):
    return tags.get(key) if isinstance(tags, dict) else None


def _clean(value):
    """Normalize a cell to ``None`` when it is missing/NaN/blank.

    Needed because pandas fills unmatched join columns with ``float('nan')``, which is
    truthy — so a plain ``a or b`` fallback would keep the NaN instead of falling through.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):  # catches float('nan') and pandas NA
            return None
    except (TypeError, ValueError):
        pass  # non-scalar (e.g. dict/list) — not missing
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _osm_id(row) -> str:
    """Build a stable OSM id like ``way/12345``."""
    otype = row.get("type") or "node"
    oid = row.get("id")
    if oid is None and isinstance(row.get("tags"), dict):
        oid = row["tags"].get("@id")
    return f"{otype}/{oid}"


def _num(value) -> float | None:
    """Extract a leading number from an OSM measurement string (e.g. ``"4.2 m"`` -> 4.2)."""
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(str(value))
    return float(m.group()) if m else None


def _int(value) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _carries(tags) -> tuple[str | None, str | None]:
    """Return ``(carries, carries_type)`` from what sits on the bridge."""
    highway = _clean(_tag(tags, "highway"))
    railway = _clean(_tag(tags, "railway"))
    waterway = _clean(_tag(tags, "waterway"))
    if highway:
        if highway in {"footway", "path", "pedestrian", "steps", "bridleway"}:
            ctype = "foot"
        elif highway == "cycleway":
            ctype = "cycle"
        else:
            ctype = "road"
        return f"highway={highway}", ctype
    if railway:
        return f"railway={railway}", "rail"
    if waterway:
        return f"waterway={waterway}", "water"
    return None, None


def to_canonical(
    gdf: gpd.GeoDataFrame,
    country: str,
    proj_crs: int = 3035,
    retrieved_at: dt.date | None = None,
) -> pd.DataFrame:
    """Map a classified bridge GeoDataFrame to the canonical schema (sorted by ``id``).

    ``proj_crs`` is the metric CRS used both for the centroid and for ``length_m`` (line
    bridges only); pass the national grid (NL: EPSG:28992) for accurate spans.
    """
    retrieved_at = retrieved_at or dt.date.today()
    if not len(gdf):
        return pd.DataFrame(columns=CANONICAL_FIELDS)

    metric = gdf.geometry.to_crs(proj_crs)
    centroids = metric.centroid.to_crs(4326)
    kinds = (
        gdf["feature_kind"]
        if "feature_kind" in gdf.columns
        else pd.Series(["carriageway"] * len(gdf), index=gdf.index)
    )

    records: list[dict] = []
    for (_, row), geom_m, cx, cy, kind in zip(
        gdf.iterrows(), metric, centroids.x, centroids.y, kinds
    ):
        tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
        otype = row.get("type") or "way"
        bridge = _clean(_tag(tags, "bridge"))
        movable = _clean(_tag(tags, "bridge:movable"))
        carries, carries_type = _carries(tags)

        # Span length only makes sense for line-mapped bridges; fall back to a length tag.
        length_m = None
        if geom_m is not None and geom_m.geom_type in ("LineString", "MultiLineString"):
            length_m = round(float(geom_m.length), 1)
        elif _num(_tag(tags, "length")) is not None:
            length_m = _num(_tag(tags, "length"))

        rec = {
            "id": _osm_id(row),
            "name": _clean(_tag(tags, "name")) or _clean(_tag(tags, "bridge:name")),
            "country": country,
            "lat": round(float(cy), 6),
            "lon": round(float(cx), 6),
            "feature_kind": kind,
            "bridge_type": bridge or ("structure" if kind == "structure" else None),
            "structure": _clean(_tag(tags, "bridge:structure")),
            "movable": movable,
            "is_movable": bool(bridge == "movable" or movable),
            "carries": carries,
            "carries_type": carries_type,
            "ref": _clean(_tag(tags, "ref")),
            "layer": _int(_tag(tags, "layer")),
            "length_m": length_m,
            "width_m": _num(_tag(tags, "width")),
            "maxweight_t": _num(_tag(tags, "maxweight")),
            "maxheight_m": _num(_tag(tags, "maxheight")),
            "material": _clean(_tag(tags, "material")),
            "operator": _clean(_tag(tags, "operator")),
            "start_date": _clean(_tag(tags, "start_date")),
            "source": "osm",
            "osm_url": f"https://www.openstreetmap.org/{otype}/{row.get('id')}",
            "data_retrieved_at": retrieved_at,
        }
        records.append(Bridge(**rec).model_dump())

    df = pd.DataFrame(records, columns=CANONICAL_FIELDS)
    if len(df):
        df = df.drop_duplicates(subset="id").sort_values("id").reset_index(drop=True)
    return df


def attach_geometry(df: pd.DataFrame, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Re-attach full WGS84 geometry to a canonical DataFrame, keyed by ``id``."""
    geom_by_id = {_osm_id(row): row.geometry for _, row in gdf.iterrows()}
    geoms = [geom_by_id.get(i) for i in df["id"]]
    return gpd.GeoDataFrame(df.copy(), geometry=gpd.GeoSeries(geoms, crs=4326))
