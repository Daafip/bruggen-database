"""Path B — Geofabrik ``.osm.pbf`` extract: versioned, offline, scales to all of Europe.

The dated ``.pbf`` *is* the reproducible snapshot — no rate limits, no API drift. We
import ``pyrosm`` lazily so the rest of the package (and the test suite) does not require
the heavy offline-parsing stack to be installed.
"""

from __future__ import annotations

import pathlib
import urllib.request

from .config import CountryConfig


def download_extract(
    cfg: CountryConfig, raw_dir: str | pathlib.Path = "data/raw"
) -> pathlib.Path:
    """Download the country's Geofabrik extract if not already present; return its path.

    The filename carries no date — Geofabrik's ``-latest`` URL is mutable — so record the
    download date in run metadata (see :mod:`restspots.pipeline`) to keep provenance.
    """
    if not cfg.geofabrik_url:
        raise ValueError(f"No geofabrik_url configured for {cfg.iso}")
    raw_dir = pathlib.Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / pathlib.Path(cfg.geofabrik_url).name
    if not dest.exists():
        urllib.request.urlretrieve(cfg.geofabrik_url, dest)  # noqa: S310 (trusted host)
    return dest


def extract_from_pbf(pbf_path: str | pathlib.Path, cfg: CountryConfig):
    """Parse rest stops and playgrounds out of a ``.pbf`` with pyrosm.

    Returns ``(rest, play)`` as GeoDataFrames, mirroring the Overpass two-layer split so
    downstream code in :mod:`restspots.join` is source-agnostic.
    """
    from pyrosm import OSM  # lazy: optional heavy dependency

    osm = OSM(str(pbf_path))
    highway_values = cfg.stop_tags.get("highway", ["services", "rest_area"])
    rest = osm.get_data_by_custom_criteria(
        custom_filter={"highway": list(highway_values)},
        filter_type="keep",
        keep_nodes=True,
        keep_ways=True,
        keep_relations=True,
    )
    play = osm.get_data_by_custom_criteria(
        custom_filter={"leisure": ["playground"]},
        filter_type="keep",
        keep_nodes=True,
        keep_ways=True,
        keep_relations=True,
    )
    return rest, play
