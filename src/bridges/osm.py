"""Low-level OSM access shared by the bridge pipeline.

Two extract paths feed the same downstream code:

* **Overpass API** — quick, iterative; raw responses are cached so a re-run never re-hits
  the public endpoint (etiquette: a descriptive User-Agent and a generous timeout).
* **Geofabrik ``.pbf``** — a dated, offline snapshot streamed with pyosmium; the reliable
  route for a whole country (a country-wide Overpass query times out).

Both ultimately yield a GeoDataFrame with ``[tags, type, id, geometry]``, so everything
downstream is source-agnostic.
"""

from __future__ import annotations

import pathlib
import urllib.request

import geopandas as gpd
from osm2geojson import json2geojson

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRROR = "https://overpass.kumi.systems/api/interpreter"
HEADERS = {
    "User-Agent": "bruggen-database/0.1 (https://github.com/HKV-products-services/bruggen-database)"
}


def merge_elements(jsons: list[dict]) -> dict:
    """Merge several Overpass responses into one, de-duplicating by ``(type, id)``."""
    seen: set[tuple] = set()
    merged: list[dict] = []
    for j in jsons:
        for el in j.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(el)
    return {"elements": merged}


def to_gdf(overpass_json: dict) -> gpd.GeoDataFrame:
    """Convert raw Overpass JSON to a WGS84 GeoDataFrame (tags under the ``tags`` column)."""
    fc = json2geojson(overpass_json)
    if not fc.get("features"):
        return gpd.GeoDataFrame(
            {"tags": [], "type": [], "id": []}, geometry=[], crs=4326
        )
    gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=4326)
    if "tags" not in gdf.columns:
        gdf["tags"] = [{} for _ in range(len(gdf))]
    return gdf


def download_extract(cfg, raw_dir: str | pathlib.Path = "data/raw") -> pathlib.Path:
    """Download the country's Geofabrik extract if not already present; return its path.

    The filename carries no date — Geofabrik's ``-latest`` URL is mutable — so record the
    download date in run metadata (see :mod:`bridges.pipeline`) to keep provenance.
    """
    if not cfg.geofabrik_url:
        raise ValueError(f"No geofabrik_url configured for {cfg.iso}")
    raw_dir = pathlib.Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / pathlib.Path(cfg.geofabrik_url).name
    if not dest.exists():
        urllib.request.urlretrieve(cfg.geofabrik_url, dest)  # noqa: S310 (trusted host)
    return dest


def way_geometry(way):
    """Build a shapely geometry for a way from its (located) nodes; None if unusable."""
    from shapely.geometry import LineString, Point, Polygon

    coords = [(n.location.lon, n.location.lat) for n in way.nodes if n.location.valid()]
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return Polygon(coords)
    if len(coords) >= 2:
        return LineString(coords)
    if coords:
        return Point(coords[0])
    return None
