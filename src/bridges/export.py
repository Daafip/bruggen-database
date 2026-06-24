"""Export the canonical bridge dataset to three formats: GeoJSON, KML, CSV+WKT.

CSV/KML do **not** hard-fail past the My Maps 2,000-row cap: a national bridge set is tens
of thousands of rows and is a legitimate full-database deliverable. The cap is reported as a
warning instead, so the caller knows to split per province/type before loading into My Maps
(GeoJSON / the Datasets API have no such cap).
"""

from __future__ import annotations

import pathlib
import sys

import geopandas as gpd
import pandas as pd
import simplekml

MYMAPS_ROW_LIMIT = 2000


def write_geojson(gdf: gpd.GeoDataFrame, path: str | pathlib.Path) -> pathlib.Path:
    """Write RFC 7946 GeoJSON (for the Maps JS API / Datasets API / any GIS)."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    return path


def _warn_mymaps(n: int) -> None:
    if n > MYMAPS_ROW_LIMIT:
        print(
            f"  ! [export] {n} rows exceeds the My Maps {MYMAPS_ROW_LIMIT}-row layer "
            "limit; split per province/type before importing into My Maps "
            "(GeoJSON / Datasets API have no such cap).",
            file=sys.stderr,
        )


def write_csv_wkt(
    df: pd.DataFrame | gpd.GeoDataFrame, path: str | pathlib.Path
) -> pathlib.Path:
    """Write CSV with a ``WKT`` column (+ ``latitude``/``longitude``) for sheets / My Maps."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if isinstance(out, gpd.GeoDataFrame) and out.geometry is not None:
        out["WKT"] = out.geometry.apply(lambda g: g.wkt if g is not None else "")
        out["latitude"] = out.get("lat", out.geometry.centroid.y)
        out["longitude"] = out.get("lon", out.geometry.centroid.x)
        out = pd.DataFrame(out.drop(columns="geometry"))
    else:
        out["WKT"] = [f"POINT ({lon} {lat})" for lon, lat in zip(out["lon"], out["lat"])]
        out["latitude"] = out["lat"]
        out["longitude"] = out["lon"]
    _warn_mymaps(len(out))
    out.to_csv(path, index=False)
    return path


def write_kml(
    df: pd.DataFrame | gpd.GeoDataFrame, path: str | pathlib.Path
) -> pathlib.Path:
    """Write KML points (lon,lat order) describing each bridge's key attributes."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kml = simplekml.Kml()
    for _, r in df.iterrows():
        p = kml.newpoint(name=(r.get("name") or r.get("bridge_type") or "Bridge"))
        p.coords = [(r["lon"], r["lat"])]
        movable = f"\nMovable: {r.get('movable')}" if r.get("movable") else ""
        length = f"\nLength: {r.get('length_m')} m" if pd.notna(r.get("length_m")) else ""
        p.description = (
            f"Type: {r.get('bridge_type') or '?'} ({r.get('feature_kind') or '?'})\n"
            f"Structure: {r.get('structure') or '?'}{movable}\n"
            f"Carries: {r.get('carries') or '?'}"
            f"{length}\n"
            f"{r.get('osm_url') or ''}"
        )
    _warn_mymaps(len(df))
    kml.save(str(path))
    return path


def write_all(
    gdf: gpd.GeoDataFrame, df: pd.DataFrame, out_dir: str | pathlib.Path, country: str
) -> dict[str, pathlib.Path]:
    """Write all three formats for one country; return the paths by format."""
    out_dir = pathlib.Path(out_dir)
    stem = f"bridges_{country}"
    return {
        "geojson": write_geojson(gdf, out_dir / f"{stem}.geojson"),
        "kml": write_kml(df, out_dir / f"{stem}.kml"),
        "csv": write_csv_wkt(df, out_dir / f"{stem}.csv"),
    }
