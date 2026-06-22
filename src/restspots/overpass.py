"""Path A — Overpass API: quick, iterative extraction with raw-response caching.

Etiquette baked in: a descriptive User-Agent, a generous timeout, and idempotent
caching so a re-run never re-hits the public endpoint. For heavy/repeated use point
``endpoint`` at a mirror or switch to Path B (:mod:`restspots.pbf`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

import requests

from .config import CountryConfig

ENDPOINT = "https://overpass-api.de/api/interpreter"
MIRROR = "https://overpass.kumi.systems/api/interpreter"
HEADERS = {
    "User-Agent": "restspots-playgrounds/0.1 (https://github.com/HKV-products-services/Speeltuinen_langs_snelweg)"
}


def build_query(cfg: CountryConfig, around_m: int = 300, timeout: int = 300) -> str:
    """Build an Overpass query for a country from its config.

    Mirrors ``queries/rest_and_playgrounds_DE.overpassql`` but is generated from the
    YAML so any configured country works without a hand-written query file.
    """
    highway_values = cfg.stop_tags.get("highway", ["services", "rest_area"])
    stop_lines = "\n  ".join(f'nwr["highway"="{v}"](area.cc);' for v in highway_values)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"area{cfg.osm_area}->.cc;\n"
        f"(\n  {stop_lines}\n)->.rest;\n"
        f'(\n  nwr["leisure"="playground"](around.rest:{around_m});\n)->.play;\n'
        f".rest out geom;\n"
        f".play out geom;\n"
    )


def load_query_file(path: str | pathlib.Path) -> str:
    """Read a committed ``.overpassql`` query (the version-controlled snapshot of intent)."""
    return pathlib.Path(path).read_text()


def _cache_path(
    query: str, country: str, raw_dir: pathlib.Path, today: dt.date
) -> pathlib.Path:
    qhash = hashlib.sha1(query.encode()).hexdigest()[:8]
    return raw_dir / f"osm_{country}_{today.isoformat()}_{qhash}.json"


def run_overpass(
    query: str,
    country: str,
    raw_dir: str | pathlib.Path = "data/raw",
    endpoint: str = ENDPOINT,
    today: dt.date | None = None,
) -> dict:
    """POST a query and cache the raw JSON under a dated, content-hashed name.

    The cache key is ``(country, date, sha1(query)[:8])`` so changing the query or the
    day produces a new file, but a same-day re-run of the same query is served offline.
    """
    raw_dir = pathlib.Path(raw_dir)
    today = today or dt.date.today()
    out = _cache_path(query, country, raw_dir, today)
    if out.exists():  # idempotent: never re-hit a cached snapshot
        return json.loads(out.read_text())
    resp = requests.post(endpoint, data={"data": query}, headers=HEADERS, timeout=360)
    resp.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(resp.text)
    return resp.json()
