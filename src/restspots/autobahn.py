"""Autobahn GmbH API — German federal open data, used to enrich OSM stops.

The road list comes from the base endpoint; ``…/services/parking_lorry`` returns the
official Rastplätze for each road, which we later match spatially to OSM stops to attach
an official name + motorway ref. Responses are cached under ``data/raw/`` exactly like
Overpass so a build is reproducible offline.

Base: https://verkehr.autobahn.de/o/autobahn
"""

from __future__ import annotations

import json
import pathlib

import requests

BASE = "https://verkehr.autobahn.de/o/autobahn"
HEADERS = {"User-Agent": "restspots-playgrounds/0.1"}

# The road list contains a combined "A1/A59" entry that the per-road endpoints reject.
SKIP_ROADS = {"A1/A59"}


def list_roads(cache_dir: str | pathlib.Path = "data/raw") -> list[str]:
    """Return the list of motorway identifiers (e.g. ``["A1", "A2", ...]``), cached."""
    cache_dir = pathlib.Path(cache_dir)
    cache = cache_dir / "autobahn_roads.json"
    if cache.exists():
        roads = json.loads(cache.read_text())["roads"]
    else:
        data = requests.get(f"{BASE}/", headers=HEADERS, timeout=30).json()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
        roads = data["roads"]
    return [r for r in roads if r not in SKIP_ROADS]


def rest_areas(road: str, cache_dir: str | pathlib.Path = "data/raw") -> list[dict]:
    """Return the official Rastplätze for one road, cached per road."""
    cache_dir = pathlib.Path(cache_dir)
    cache = cache_dir / f"autobahn_{road.replace('/', '_')}_parking_lorry.json"
    if cache.exists():
        return json.loads(cache.read_text()).get("parking_lorry", [])
    r = requests.get(
        f"{BASE}/{road}/services/parking_lorry", headers=HEADERS, timeout=30
    )
    if not r.ok:
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text)
    return r.json().get("parking_lorry", [])


def fetch_all(cache_dir: str | pathlib.Path = "data/raw") -> list[dict]:
    """Fetch every road's Rastplätze, each annotated with its road ref."""
    out: list[dict] = []
    for road in list_roads(cache_dir):
        for item in rest_areas(road, cache_dir):
            item = dict(item)
            item.setdefault("road", road)
            out.append(item)
    return out


def to_points(items: list[dict]):
    """Convert Autobahn parking_lorry records into a point GeoDataFrame.

    Implements the connector interface shared by every national source:
    ``to_points(raw) -> GeoDataFrame[name, ref, geometry]``.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    records, geoms = [], []
    for it in items:
        coord = it.get("coordinate") or {}
        try:
            lon = float(coord["long"])
            lat = float(coord["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        records.append({"name": it.get("title", ""), "ref": it.get("road", "")})
        geoms.append(Point(lon, lat))
    return gpd.GeoDataFrame(records, geometry=geoms, crs=4326)
