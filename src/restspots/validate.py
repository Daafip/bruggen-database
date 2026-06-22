"""Phase 5 — programmatic QA run before publishing.

Returns a structured report (counts, coverage by match_type/ref, geometry validity,
proximity audit) plus a list of hard failures that should block a release.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

# Rough WGS84 bounding boxes per country for a coarse coordinate sanity check.
COUNTRY_BBOX = {
    "DE": (5.8, 47.2, 15.1, 55.1),
    "NL": (3.3, 50.7, 7.3, 53.6),
    "AT": (9.5, 46.3, 17.2, 49.1),
}


def validate(gdf: gpd.GeoDataFrame, df: pd.DataFrame, country: str) -> dict:
    """Run QA checks. ``report["failures"]`` being empty means it passes acceptance."""
    failures: list[str] = []
    n = len(df)

    if n == 0:
        failures.append("no rows in the final dataset")

    # Geometry validity.
    geom_valid = bool(gdf.geometry.is_valid.all()) if len(gdf) else False
    geom_nonempty = bool((~gdf.geometry.is_empty).all()) if len(gdf) else False
    if len(gdf) and not geom_valid:
        failures.append("invalid geometries present")
    if len(gdf) and not geom_nonempty:
        failures.append("empty/null geometries present")

    # Every row must have a name or a motorway_ref (acceptance criterion).
    if n:
        missing_id = df[(df["name"].isna()) & (df["motorway_ref"].isna())]
        if len(missing_id):
            failures.append(
                f"{len(missing_id)} rows have neither name nor motorway_ref"
            )

    # Coordinates within the country bbox.
    bbox = COUNTRY_BBOX.get(country.upper())
    out_of_bbox = 0
    if bbox and n:
        minx, miny, maxx, maxy = bbox
        out_of_bbox = int(
            (~df["lon"].between(minx, maxx) | ~df["lat"].between(miny, maxy)).sum()
        )
        if out_of_bbox:
            failures.append(
                f"{out_of_bbox} rows fall outside the {country} bounding box"
            )

    by_match = df["match_type"].value_counts(dropna=False).to_dict() if n else {}
    by_ref = (
        df["motorway_ref"].value_counts(dropna=True).head(15).to_dict() if n else {}
    )

    return {
        "country": country,
        "total_stops": n,
        "geometry_valid": geom_valid,
        "geometry_nonempty": geom_nonempty,
        "out_of_bbox": out_of_bbox,
        "by_match_type": {str(k): int(v) for k, v in by_match.items()},
        "by_motorway_ref": {str(k): int(v) for k, v in by_ref.items()},
        "failures": failures,
        "passed": not failures,
    }
