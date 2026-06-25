"""Bridge Overpass query builder + country fetch.

A bridge query has a single result set (no sub-query), so fetching is simple: build the
query, POST it, and cache the raw JSON under a dated, content-hashed name. Per-region
responses are merged when a country is fetched in pieces.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sys

from . import osm
from .config import BridgeConfig


def build_query(
    cfg: BridgeConfig,
    timeout: int = 300,
    area: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> str:
    """Build an Overpass query for every bridge in an area, plus the waterways it may cross.

    Selects ways carrying a ``bridge`` tag (other than ``no``) — the carriageway on the
    bridge — plus ``man_made=bridge`` ways/relations (the structure outline), and river /
    canal / stream centrelines (used to detect bridges crossing the *same* body of water).

    ``area`` overrides the country boundary selector (e.g. an ISO3166-2 region) for
    piecewise fetching; ``bbox`` (``south, west, north, east`` in WGS84) restricts to a
    bounding box instead — handy for fast iterative testing.
    """
    water = 'way["waterway"~"^(river|canal|stream)$"]'
    if bbox is not None:
        s, w, n, e = bbox
        scope = f"({s},{w},{n},{e})"
        return (
            f"[out:json][timeout:{timeout}];\n"
            f"(\n"
            f'  way["bridge"]["bridge"!="no"]{scope};\n'
            f'  way["man_made"="bridge"]{scope};\n'
            f'  relation["man_made"="bridge"]{scope};\n'
            f"  {water}{scope};\n"
            f");\n"
            f"out geom;\n"
        )
    area = area or cfg.osm_area
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"area{area}->.cc;\n"
        f"(\n"
        f'  way["bridge"]["bridge"!="no"](area.cc);\n'
        f'  way["man_made"="bridge"](area.cc);\n'
        f'  relation["man_made"="bridge"](area.cc);\n'
        f"  {water}(area.cc);\n"
        f");\n"
        f"out geom;\n"
    )


def _cache_path(
    query: str, country: str, raw_dir: pathlib.Path, today: dt.date
) -> pathlib.Path:
    """Dated, content-hashed cache name (``osm_bridges_<C>_<date>_<hash>.json``)."""
    qhash = hashlib.sha1(query.encode()).hexdigest()[:8]
    return raw_dir / f"osm_bridges_{country}_{today.isoformat()}_{qhash}.json"


def fetch_country(
    cfg: BridgeConfig,
    raw_dir: str | pathlib.Path = "data/raw",
    endpoint: str = osm.ENDPOINT,
    query_timeout: int = 300,
    read_timeout: int = 360,
    today: dt.date | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[pathlib.Path, dict]:
    """Fetch a country's bridges as one query, or per-region and merged if configured.

    Returns ``(snapshot_path, overpass_json)``. A failed region is logged and skipped
    (never silently), and the merged snapshot is cached under ``osm_bridges_<ISO>_…`` so
    :mod:`bridges.pipeline` picks it up unchanged.
    """
    raw_dir = pathlib.Path(raw_dir)
    today = today or dt.date.today()

    if bbox is not None:
        query = build_query(cfg, timeout=query_timeout, bbox=bbox)
        data = _run(query, f"{cfg.iso}-bbox", raw_dir, endpoint, today, read_timeout)
        return _cache_path(query, f"{cfg.iso}-bbox", raw_dir, today), data

    if not cfg.regions:
        query = build_query(cfg, timeout=query_timeout)
        data = _run(query, cfg.iso, raw_dir, endpoint, today, read_timeout)
        return _cache_path(query, cfg.iso, raw_dir, today), data

    parts: list[dict] = []
    skipped: list[str] = []
    for region in cfg.regions:
        label = region.split("=")[-1].strip('"]')
        query = build_query(cfg, timeout=query_timeout, area=region)
        try:
            data = _run(query, label, raw_dir, endpoint, today, read_timeout)
            parts.append(data)
            print(f"  [fetch] {label}: {len(data.get('elements', []))} elements")
        except Exception as exc:  # noqa: BLE001 — transparency over completeness
            skipped.append(label)
            print(f"  ! [fetch] {label} failed: {exc}", file=sys.stderr)

    if skipped:
        print(f"  ! [fetch] skipped regions: {', '.join(skipped)}", file=sys.stderr)
    merged = osm.merge_elements(parts)
    out = _cache_path("MERGED:" + ",".join(cfg.regions), cfg.iso, raw_dir, today)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged))
    return out, merged


def _run(query, label, raw_dir, endpoint, today, read_timeout) -> dict:
    """POST a query and cache the raw JSON under ``osm_bridges_<label>_<date>_<hash>.json``.

    Idempotent: a same-day re-run of the same query is served from the cache, never
    re-hitting the public endpoint.
    """
    import requests

    out = _cache_path(query, label, raw_dir, today)
    if out.exists():  # idempotent: never re-hit a cached snapshot
        return json.loads(out.read_text())
    resp = requests.post(
        endpoint,
        data={"data": query},
        headers=osm.HEADERS,
        timeout=read_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    # Overpass reports server-side failures as a 200 with a `remark`, not an HTTP error.
    remark = str(data.get("remark", "")).lower()
    if "runtime error" in remark or "timed out" in remark:
        raise RuntimeError(f"Overpass query failed: {data['remark']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(resp.text)
    return data
