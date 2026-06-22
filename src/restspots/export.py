"""Phase 4 — export the canonical dataset to the three Google-consumable formats.

One canonical schema, three serializers. **My Maps does not accept GeoJSON**, so we
always ship KML + CSV alongside it.

| Format       | Consumes into                                          |
|--------------|--------------------------------------------------------|
| GeoJSON      | Maps JavaScript API Data layer; Maps Datasets API; GIS |
| KML          | Google My Maps; Google Earth                           |
| CSV + WKT    | Google My Maps; spreadsheets                           |

My Maps limits to respect: <= 2,000 rows/layer, KML/KMZ <= 5 MB, CSV <= 40 MB; the
geometry column must be named ``WKT``. For Germany the count of stops with playgrounds
is well under 2,000; split per country/region at EU scale.
"""

from __future__ import annotations

import pathlib

import geopandas as gpd
import pandas as pd
import simplekml

MYMAPS_ROW_LIMIT = 2000


def write_geojson(gdf: gpd.GeoDataFrame, path: str | pathlib.Path) -> pathlib.Path:
    """Write RFC 7946 GeoJSON for the Maps JS API / Datasets API."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    return path


def write_csv_wkt(
    df: pd.DataFrame | gpd.GeoDataFrame, path: str | pathlib.Path
) -> pathlib.Path:
    """Write CSV with a ``WKT`` column (+ ``latitude``/``longitude``) for My Maps / sheets."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if isinstance(out, gpd.GeoDataFrame) and out.geometry is not None:
        out["WKT"] = out.geometry.apply(lambda g: g.wkt if g is not None else "")
        out["latitude"] = out.get("lat", out.geometry.centroid.y)
        out["longitude"] = out.get("lon", out.geometry.centroid.x)
        out = pd.DataFrame(out.drop(columns="geometry"))
    else:
        # Plain canonical DataFrame: build a POINT WKT from lat/lon.
        out["WKT"] = [
            f"POINT ({lon} {lat})" for lon, lat in zip(out["lon"], out["lat"])
        ]
        out["latitude"] = out["lat"]
        out["longitude"] = out["lon"]
    if len(out) > MYMAPS_ROW_LIMIT:
        # Don't truncate silently — the caller must split by country/region.
        raise ValueError(
            f"{len(out)} rows exceeds the My Maps {MYMAPS_ROW_LIMIT}-row layer limit; "
            "split the export per country/region."
        )
    out.to_csv(path, index=False)
    return path


def write_kml(
    df: pd.DataFrame | gpd.GeoDataFrame, path: str | pathlib.Path
) -> pathlib.Path:
    """Write KML points (lon,lat order handled here) for My Maps / Google Earth."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = df.iterrows()
    kml = simplekml.Kml()
    for _, r in rows:
        lat = r["lat"]
        lon = r["lon"]
        p = kml.newpoint(name=(r.get("name") or "Rest stop"), coords=[(lon, lat)])
        p.description = (
            f"Motorway: {r.get('motorway_ref') or '?'}\n"
            f"Playgrounds: {r.get('playground_count', 0)}\n"
            f"Type: {r.get('feature_type') or '?'}\n"
            f"Match: {r.get('match_type') or '?'}\n"
            f"{r.get('osm_url') or ''}"
        )
    kml.save(str(path))
    return path


def write_all(
    gdf: gpd.GeoDataFrame, df: pd.DataFrame, out_dir: str | pathlib.Path, country: str
) -> dict[str, pathlib.Path]:
    """Write all three formats for one country; return the paths by format."""
    out_dir = pathlib.Path(out_dir)
    stem = f"rest_stops_playgrounds_{country}"
    return {
        "geojson": write_geojson(gdf, out_dir / f"{stem}.geojson"),
        "kml": write_kml(df, out_dir / f"{stem}.kml"),
        "csv": write_csv_wkt(df, out_dir / f"{stem}.csv"),
    }
