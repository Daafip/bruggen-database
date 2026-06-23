"""Phase 3 — the canonical schema. The internal model never changes; only the
serializer differs per Google product (see :mod:`restspots.export`).
"""

from __future__ import annotations

import datetime as dt

import geopandas as gpd
import pandas as pd
from pydantic import BaseModel

# Family-relevant amenity tags surfaced as booleans in the output.
AMENITY_TAGS = ["toilets", "restaurant", "fuel", "cafe", "picnic", "wheelchair"]

# Truthful category label for stops that OSM leaves unnamed, so every Maps pin has a
# title. Keyed by feature_type; the German term matches what the stop actually is.
FEATURE_LABELS = {"services": "Raststätte", "rest_area": "Rastplatz"}

# Column order of the canonical (gold) dataset.
CANONICAL_FIELDS = [
    "id",
    "name",
    "country",
    "lat",
    "lon",
    "feature_type",
    "motorway_ref",
    "has_playground",
    "playground_count",
    "match_type",
    *AMENITY_TAGS,
    "source",
    "osm_url",
    "data_retrieved_at",
]


class RestStop(BaseModel):
    """One rest stop with a playground — the canonical record."""

    id: str
    name: str | None = None
    country: str
    lat: float
    lon: float
    feature_type: str
    motorway_ref: str | None = None
    has_playground: bool = True
    playground_count: int = 0
    match_type: str | None = None
    toilets: bool = False
    restaurant: bool = False
    fuel: bool = False
    cafe: bool = False
    picnic: bool = False
    wheelchair: bool = False
    source: str = "osm"
    osm_url: str | None = None
    data_retrieved_at: dt.date | None = None


def _tag(tags, key):
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


def _truthy(value) -> bool:
    """OSM-style truthiness: present and not an explicit 'no'/'false'/'0'."""
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "no", "false", "0"}


def _osm_id(row) -> str:
    """Build a stable OSM id like ``way/12345`` from osm2geojson properties."""
    otype = row.get("type") or "node"
    oid = row.get("id")
    if oid is None and isinstance(row.get("tags"), dict):
        oid = row["tags"].get("@id")
    return f"{otype}/{oid}"


def to_canonical(
    gdf: gpd.GeoDataFrame,
    country: str,
    retrieved_at: dt.date | None = None,
    official_name_col: str = "official_name",
) -> pd.DataFrame:
    """Map a joined/enriched GeoDataFrame to the canonical schema (sorted by ``id``).

    Geometry is reduced to a WGS84 centroid (``lat``/``lon``) for point placement; the
    GeoJSON exporter keeps full geometry separately.
    """
    retrieved_at = retrieved_at or dt.date.today()
    # Centroid in an equal-area metric CRS, then back to WGS84 (accurate + warning-free).
    centroids = gdf.geometry.to_crs(3035).centroid.to_crs(4326)
    records: list[dict] = []
    for (_, row), cx, cy in zip(gdf.iterrows(), centroids.x, centroids.y):
        tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
        osm_id = _osm_id(row)
        otype = row.get("type") or "node"
        feature_type = _tag(tags, "highway") or "rest_area"
        # Prefer the OSM name, then an official (enrichment) name, then a category label.
        name = (
            _clean(_tag(tags, "name"))
            or _clean(row.get(official_name_col))
            or FEATURE_LABELS.get(feature_type, "Rastplatz")
        )
        rec = {
            "id": osm_id,
            "name": name,
            "country": country,
            "lat": round(float(cy), 6),
            "lon": round(float(cx), 6),
            "feature_type": feature_type,
            "motorway_ref": _clean(row.get("motorway_ref"))
            or _clean(_tag(tags, "ref")),
            "has_playground": bool(row.get("has_playground", True)),
            "playground_count": int(row.get("playground_count", 0) or 0),
            "match_type": _clean(row.get("match_type")),
            "source": "osm",
            "osm_url": f"https://www.openstreetmap.org/{otype}/{row.get('id')}",
            "data_retrieved_at": retrieved_at,
        }
        for tag in AMENITY_TAGS:
            rec[tag] = _truthy(_tag(tags, tag))
        # Validate/coerce through pydantic, then emit a plain dict.
        records.append(RestStop(**rec).model_dump())

    df = pd.DataFrame(records, columns=CANONICAL_FIELDS)
    if len(df):
        df = df.drop_duplicates(subset="id").sort_values("id").reset_index(drop=True)
    return df


def attach_geometry(df: pd.DataFrame, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Re-attach full WGS84 geometry to a canonical DataFrame, keyed by ``id``."""
    geom_by_id = {}
    for _, row in gdf.iterrows():
        geom_by_id[_osm_id(row)] = row.geometry
    geoms = [geom_by_id.get(i) for i in df["id"]]
    # Wrap in a GeoSeries so an empty result still carries a CRS (a bare [] would not).
    return gpd.GeoDataFrame(df.copy(), geometry=gpd.GeoSeries(geoms, crs=4326))
