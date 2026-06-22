"""CLI orchestration — ``fetch -> build -> export -> validate`` per country.

Bronze/silver/gold layering keeps the pipeline reproducible: ``build`` runs entirely
off cached raw snapshots (no network), so changing a buffer radius never re-hits an API.
Run via ``pixi run all`` or ``python -m restspots.pipeline <cmd> --country DE``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import export as export_mod
from . import join, schema, validate as validate_mod
from .config import CountryConfig, get_country


# --------------------------------------------------------------------------- paths
def _paths(args) -> dict[str, pathlib.Path]:
    return {
        "raw": pathlib.Path(args.raw_dir),
        "interim": pathlib.Path(args.interim_dir),
        "processed": pathlib.Path(args.processed_dir),
    }


def _gold_path(processed: pathlib.Path, country: str) -> pathlib.Path:
    return processed / f"rest_stops_playgrounds_{country}.gold.geojson"


def _latest_raw(raw: pathlib.Path, country: str) -> pathlib.Path:
    """Most recent cached Overpass snapshot for a country (dates sort lexically)."""
    matches = sorted(raw.glob(f"osm_{country}_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"No cached OSM snapshot for {country} in {raw}/. Run `fetch` first."
        )
    return matches[-1]


# ---------------------------------------------------------------------- enrichment
def _gather_enrichment(cfg: CountryConfig, raw_dir: pathlib.Path):
    """Fetch + point-ify every configured connector into one GeoDataFrame, or None."""
    import pandas as pd

    from .enrich import CONNECTORS

    frames = []
    for key in cfg.enrichment:
        if key not in CONNECTORS:
            print(
                f"  ! unknown enrichment connector {key!r}, skipping", file=sys.stderr
            )
            continue
        fetch_fn, to_points = CONNECTORS[key]
        pts = to_points(fetch_fn(str(raw_dir)))
        if len(pts):
            pts = pts.rename(columns={"name": "official_name", "ref": "official_ref"})
            frames.append(pts[["official_name", "official_ref", "geometry"]])
    if not frames:
        return None
    import geopandas as gpd

    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)


# ------------------------------------------------------------------------ commands
def cmd_fetch(args) -> int:
    from . import overpass

    cfg = get_country(args.country, args.config)
    p = _paths(args)
    query = overpass.build_query(cfg)
    print(f"[fetch] Overpass query for {cfg.iso} -> {p['raw']}/")
    overpass.run_overpass(query, cfg.iso, raw_dir=p["raw"], endpoint=args.endpoint)
    if cfg.enrichment:
        print(f"[fetch] enrichment connectors: {', '.join(cfg.enrichment)}")
        _gather_enrichment(cfg, p["raw"])  # warms the per-source caches
    print("[fetch] done.")
    return 0


def cmd_build(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    raw_file = _latest_raw(p["raw"], cfg.iso)
    print(f"[build] reading {raw_file}")
    overpass_json = json.loads(raw_file.read_text())

    gdf = join.to_gdf(overpass_json)
    rest, play = join.split_features(gdf)
    print(f"[build] {len(rest)} rest stops, {len(play)} playgrounds")

    stops = join.attach_playgrounds(
        rest,
        play,
        contained_buf=cfg.playground_contained_buffer_m,
        proximity_buf=cfg.playground_proximity_m,
    )
    print(f"[build] {len(stops)} stops with a playground")

    points = _gather_enrichment(cfg, p["raw"]) if cfg.enrichment else None
    if points is not None and len(stops):
        stops = join.attach_nearest(
            stops, points, ["official_name", "official_ref"], 300.0
        )
        stops["motorway_ref"] = stops["official_ref"]

    retrieved_at = _snapshot_date(raw_file)
    df = schema.to_canonical(stops, cfg.iso, retrieved_at=retrieved_at)
    gold = schema.attach_geometry(df, stops)

    # silver (per-source) and gold (final) outputs.
    p["interim"].mkdir(parents=True, exist_ok=True)
    if len(stops):
        stops.to_file(p["interim"] / f"stops_{cfg.iso}.geojson", driver="GeoJSON")
    p["processed"].mkdir(parents=True, exist_ok=True)
    gold_path = _gold_path(p["processed"], cfg.iso)
    if len(gold):
        gold.to_file(gold_path, driver="GeoJSON")
    else:  # write an empty but valid file so downstream steps don't crash
        gold_path.write_text('{"type":"FeatureCollection","features":[]}')

    _write_metadata(p["processed"], cfg, raw_file, retrieved_at, len(df))
    print(f"[build] wrote gold dataset -> {gold_path} ({len(df)} rows)")
    return 0


def cmd_export(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    import geopandas as gpd

    gold_path = _gold_path(p["processed"], cfg.iso)
    if not gold_path.exists():
        raise FileNotFoundError(f"{gold_path} missing. Run `build` first.")
    gdf = gpd.read_file(gold_path)
    df = gdf.drop(columns="geometry") if "geometry" in gdf.columns else gdf
    paths = export_mod.write_all(gdf, df, p["processed"], cfg.iso)
    for fmt, path in paths.items():
        print(f"[export] {fmt:8s} -> {path}")
    return 0


def cmd_validate(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    import geopandas as gpd

    gold_path = _gold_path(p["processed"], cfg.iso)
    if not gold_path.exists():
        raise FileNotFoundError(f"{gold_path} missing. Run `build` first.")
    gdf = gpd.read_file(gold_path)
    df = gdf.drop(columns="geometry") if "geometry" in gdf.columns else gdf
    report = validate_mod.validate(gdf, df, cfg.iso)
    print(json.dumps(report, indent=2, default=str))
    if not report["passed"]:
        print("[validate] FAILED", file=sys.stderr)
        return 1
    print("[validate] OK")
    return 0


# ------------------------------------------------------------------------- helpers
def _snapshot_date(raw_file: pathlib.Path) -> dt.date:
    """Recover the OSM snapshot date from the cached filename, falling back to today."""
    parts = raw_file.stem.split("_")  # osm_DE_2026-06-22_abcd1234
    try:
        return dt.date.fromisoformat(parts[2])
    except (IndexError, ValueError):
        return dt.date.today()


def _write_metadata(processed, cfg, raw_file, retrieved_at, n_rows) -> None:
    meta = {
        "country": cfg.iso,
        "osm_snapshot_date": retrieved_at.isoformat(),
        "raw_source": str(raw_file),
        "enrichment": cfg.enrichment,
        "rows": n_rows,
        "crs_project": join.PROJ,
        "proximity_m": cfg.playground_proximity_m,
        "contained_buffer_m": cfg.playground_contained_buffer_m,
    }
    (processed / f"run_metadata_{cfg.iso}.json").write_text(json.dumps(meta, indent=2))


COMMANDS = {
    "fetch": cmd_fetch,
    "build": cmd_build,
    "export": cmd_export,
    "validate": cmd_validate,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="restspots", description=__doc__)
    parser.add_argument("command", choices=list(COMMANDS), help="pipeline stage to run")
    parser.add_argument(
        "--country", default="DE", help="ISO country code (default: DE)"
    )
    parser.add_argument("--config", default=None, help="path to countries.yml")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--interim-dir", default="data/interim")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument(
        "--endpoint", default=None, help="Overpass endpoint (defaults to public API)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.endpoint is None:
        from .overpass import ENDPOINT

        args.endpoint = ENDPOINT
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
