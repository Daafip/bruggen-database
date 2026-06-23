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


def build_query(
    cfg: CountryConfig,
    around_m: int = 300,
    timeout: int = 300,
    area: str | None = None,
) -> str:
    """Build an Overpass query for a country from its config.

    Mirrors ``queries/rest_and_playgrounds_DE.overpassql`` but is generated from the
    YAML so any configured country works without a hand-written query file. ``area``
    overrides the area selector (e.g. an ISO3166-2 state) for regional fetching.
    """
    area = area or cfg.osm_area
    highway_values = cfg.stop_tags.get("highway", ["services", "rest_area"])
    stop_lines = "\n  ".join(f'nwr["highway"="{v}"](area.cc);' for v in highway_values)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"area{area}->.cc;\n"
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
    read_timeout: int = 360,
) -> dict:
    """POST a query and cache the raw JSON under a dated, content-hashed name.

    The cache key is ``(country, date, sha1(query)[:8])`` so changing the query or the
    day produces a new file, but a same-day re-run of the same query is served offline.
    ``read_timeout`` should comfortably exceed the query's own ``[timeout:...]`` so the
    client waits out the server's queue + execution (large countries need a mirror).
    """
    raw_dir = pathlib.Path(raw_dir)
    today = today or dt.date.today()
    out = _cache_path(query, country, raw_dir, today)
    if out.exists():  # idempotent: never re-hit a cached snapshot
        return json.loads(out.read_text())
    resp = requests.post(
        endpoint, data={"data": query}, headers=HEADERS, timeout=read_timeout
    )
    resp.raise_for_status()
    data = resp.json()
    # Overpass reports server-side failures as a 200 with a `remark`, NOT an HTTP error.
    # Treat a timeout/error remark as a failure so we don't cache an empty result that
    # looks like "0 stops" — and so a retry (longer timeout / mirror / Path B) can run.
    remark = str(data.get("remark", "")).lower()
    if "runtime error" in remark or "timed out" in remark:
        raise RuntimeError(f"Overpass query failed: {data['remark']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(resp.text)
    return data


def merge_elements(jsons: list[dict]) -> dict:
    """Merge several Overpass responses into one, de-duplicating by (type, id)."""
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


def fetch_country(
    cfg: CountryConfig,
    raw_dir: str | pathlib.Path = "data/raw",
    endpoint: str = ENDPOINT,
    query_timeout: int = 300,
    read_timeout: int = 360,
    today: dt.date | None = None,
) -> tuple[pathlib.Path, dict]:
    """Fetch a country as one query, or per-region and merged if ``cfg.regions`` is set.

    Returns ``(snapshot_path, overpass_json)``. Per-region responses are cached
    individually (``osm_<region>_…``); the merged snapshot is written as
    ``osm_<ISO>_…`` so :mod:`restspots.pipeline` picks it up unchanged. A region that
    fails is logged and skipped (never silently) so the run still produces a dataset.
    """
    import sys

    raw_dir = pathlib.Path(raw_dir)
    today = today or dt.date.today()

    if not cfg.regions:
        query = build_query(cfg, timeout=query_timeout)
        data = run_overpass(query, cfg.iso, raw_dir, endpoint, today, read_timeout)
        return _cache_path(query, cfg.iso, raw_dir, today), data

    parts: list[dict] = []
    skipped: list[str] = []
    for region in cfg.regions:
        label = region.split("=")[-1].strip('"]')  # e.g. DE-BW
        query = build_query(cfg, timeout=query_timeout, area=region)
        try:
            data = run_overpass(query, label, raw_dir, endpoint, today, read_timeout)
            parts.append(data)
            print(f"  [fetch] {label}: {len(data.get('elements', []))} elements")
        except Exception as exc:  # noqa: BLE001 — transparency over completeness
            skipped.append(label)
            print(f"  ! [fetch] {label} failed: {exc}", file=sys.stderr)

    if skipped:
        print(f"  ! [fetch] skipped regions: {', '.join(skipped)}", file=sys.stderr)
    merged = merge_elements(parts)
    out = _cache_path("MERGED:" + ",".join(cfg.regions), cfg.iso, raw_dir, today)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged))
    return out, merged
