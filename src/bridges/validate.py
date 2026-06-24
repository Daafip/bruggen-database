"""QA run for the bridge dataset before publishing.

Returns a structured report (counts, breakdowns by type/carries/kind, the movable-bridge
headline figure, geometry validity, bbox check) plus a list of hard failures that block a
release. Note: unlike rest stops, a bridge need not have a name — most are unnamed — so the
"name or ref" rule does not apply here.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

# Rough WGS84 bounding boxes per country for a coarse coordinate sanity check.
COUNTRY_BBOX = {
    "NL": (3.3, 50.7, 7.3, 53.6),
}


def validate(gdf: gpd.GeoDataFrame, df: pd.DataFrame, country: str) -> dict:
    """Run QA checks. ``report["failures"]`` being empty means it passes acceptance."""
    failures: list[str] = []
    n = len(df)

    if n == 0:
        failures.append("no rows in the final dataset")

    geom_valid = bool(gdf.geometry.is_valid.all()) if len(gdf) else False
    geom_nonempty = bool((~gdf.geometry.is_empty).all()) if len(gdf) else False
    if len(gdf) and not geom_valid:
        failures.append("invalid geometries present")
    if len(gdf) and not geom_nonempty:
        failures.append("empty/null geometries present")

    bbox = COUNTRY_BBOX.get(country.upper())
    out_of_bbox = 0
    if bbox and n:
        minx, miny, maxx, maxy = bbox
        out_of_bbox = int(
            (~df["lon"].between(minx, maxx) | ~df["lat"].between(miny, maxy)).sum()
        )
        if out_of_bbox:
            failures.append(f"{out_of_bbox} rows fall outside the {country} bounding box")

    def _counts(col: str, top: int | None = None) -> dict:
        if not n or col not in df.columns:
            return {}
        vc = df[col].value_counts(dropna=False)
        if top:
            vc = vc.head(top)
        return {str(k): int(v) for k, v in vc.items()}

    return {
        "country": country,
        "total_bridges": n,
        "movable_bridges": int(df["is_movable"].sum()) if n else 0,
        "named": int(df["name"].notna().sum()) if n else 0,
        "geometry_valid": geom_valid,
        "geometry_nonempty": geom_nonempty,
        "out_of_bbox": out_of_bbox,
        "by_feature_kind": _counts("feature_kind"),
        "by_bridge_type": _counts("bridge_type"),
        "by_carries_type": _counts("carries_type"),
        "by_structure": _counts("structure", top=10),
        "failures": failures,
        "passed": not failures,
    }
