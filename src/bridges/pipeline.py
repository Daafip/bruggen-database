"""CLI orchestration for the bridge database — ``fetch -> build -> export -> validate``.

Bronze/silver/gold layering keeps it reproducible: ``build`` runs entirely off cached raw
snapshots (no network). Run via ``pixi run bridges-all`` or
``python -m bridges.pipeline <cmd> --country NL``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import export as export_mod
from . import extract, group, osm, schema
from . import validate as validate_mod
from .config import get_country


# --------------------------------------------------------------------------- paths
def _paths(args) -> dict[str, pathlib.Path]:
    return {
        "raw": pathlib.Path(args.raw_dir),
        "interim": pathlib.Path(args.interim_dir),
        "processed": pathlib.Path(args.processed_dir),
    }


def _gold_path(processed: pathlib.Path, country: str) -> pathlib.Path:
    return processed / f"bridges_{country}.gold.geojson"


def _latest_raw(raw: pathlib.Path, country: str) -> pathlib.Path:
    """Most recent cached bridge Overpass snapshot for a country (dates sort lexically)."""
    matches = sorted(raw.glob(f"osm_bridges_{country}_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"No cached bridge snapshot for {country} in {raw}/. Run `fetch` first."
        )
    return matches[-1]


def _bbox(args) -> tuple[float, float, float, float] | None:
    if not getattr(args, "bbox", None):
        return None
    parts = [float(x) for x in args.bbox.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be 'south,west,north,east'")
    return tuple(parts)  # type: ignore[return-value]


# ------------------------------------------------------------------------ commands
def cmd_fetch(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    bbox = _bbox(args)

    if getattr(args, "source", "overpass") == "pbf":
        print(f"[fetch] downloading Geofabrik extract for {cfg.iso} -> {p['raw']}/")
        dest = osm.download_extract(cfg, p["raw"])
        print(f"[fetch] OSM snapshot: {dest}")
    else:
        from . import query

        mode = (
            "bbox"
            if bbox
            else (f"{len(cfg.regions)} regions" if cfg.regions else "single query")
        )
        print(
            f"[fetch] OSM bridges for {cfg.iso} ({mode}) -> {p['raw']}/ via {args.endpoint}"
        )
        _, data = query.fetch_country(
            cfg,
            raw_dir=p["raw"],
            endpoint=args.endpoint,
            query_timeout=args.query_timeout,
            read_timeout=args.read_timeout,
            bbox=bbox,
        )
        print(f"[fetch] OSM snapshot: {len(data.get('elements', []))} elements")
    print("[fetch] done.")
    return 0


def _load_bridges(args, cfg, p):
    """Return ``(bridges, waterways, raw_path, retrieved_at)`` for the selected extract path."""
    if getattr(args, "source", "overpass") == "pbf":
        if getattr(args, "pbf", None):
            pbf_path = pathlib.Path(args.pbf)
        else:
            print(f"[build] ensuring Geofabrik extract for {cfg.iso} (large download)")
            pbf_path = osm.download_extract(cfg, p["raw"])
        print(f"[build] streaming {pbf_path} with pyosmium")
        gdf, waterways = extract.from_pbf(pbf_path, cfg)
        return gdf, waterways, pbf_path, dt.date.today()

    raw_file = (
        _latest_raw(p["raw"], cfg.iso)
        if not _bbox(args)
        else _latest_raw_bbox(p["raw"], cfg.iso)
    )
    print(f"[build] reading {raw_file}")
    gdf, waterways = extract.from_overpass(json.loads(raw_file.read_text()))
    return gdf, waterways, raw_file, _snapshot_date(raw_file)


def _latest_raw_bbox(raw: pathlib.Path, country: str) -> pathlib.Path:
    matches = sorted(raw.glob(f"osm_bridges_{country}-bbox_*.json"))
    if not matches:
        raise FileNotFoundError(
            f"No cached bbox bridge snapshot for {country} in {raw}/. Run `fetch --bbox` first."
        )
    return matches[-1]


def cmd_build(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    gdf, waterways, raw_file, retrieved_at = _load_bridges(args, cfg, p)
    print(f"[build] {len(gdf)} bridge features, {len(waterways)} waterways")

    df = schema.to_canonical(
        gdf, cfg.iso, proj_crs=cfg.proj_crs, retrieved_at=retrieved_at
    )
    gold = schema.attach_geometry(df, gdf)

    # Collapse the OSM features that make up one physical bridge into a shared group_id:
    # adjacent same-type segments, divided-road carriageways over the same waterway, and
    # same-name parts — so the data/map stop double-counting.
    gold = group.assign_groups(
        gold,
        waterways=waterways,
        distance_m=cfg.group_distance_m,
        water_distance_m=cfg.group_water_distance_m,
        name_distance_m=cfg.group_name_distance_m,
        merge_distance_m=cfg.group_merge_distance_m,
        crs=cfg.proj_crs,
        country=cfg.iso,
    )
    if len(gold):
        n_groups = gold["group_id"].nunique()
        print(f"[build] grouped {len(gold)} features into {n_groups} physical bridges")

    p["interim"].mkdir(parents=True, exist_ok=True)
    if len(gdf):
        gdf.to_file(p["interim"] / f"bridges_{cfg.iso}.geojson", driver="GeoJSON")
    p["processed"].mkdir(parents=True, exist_ok=True)
    gold_path = _gold_path(p["processed"], cfg.iso)
    if len(gold):
        gold.to_file(gold_path, driver="GeoJSON")
    else:
        gold_path.write_text('{"type":"FeatureCollection","features":[]}\n')

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


def cmd_viewer(args) -> int:
    cfg = get_country(args.country, args.config)
    p = _paths(args)
    from . import viewer

    csv_path = p["processed"] / f"bridges_{cfg.iso}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} missing. Run `export` first.")
    out = viewer.build_viewer(
        csv_path, p["processed"] / f"bridges_{cfg.iso}_viewer.html", country=cfg.iso
    )
    size_mb = out.stat().st_size / 1e6
    print(f"[viewer] wrote {out} ({size_mb:.1f} MB)")
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
    parts = raw_file.stem.split("_")  # osm_bridges_NL_2026-06-24_abcd1234
    for token in parts:
        try:
            return dt.date.fromisoformat(token)
        except ValueError:
            continue
    return dt.date.today()


def _write_metadata(processed, cfg, raw_file, retrieved_at, n_rows) -> None:
    meta = {
        "country": cfg.iso,
        "osm_snapshot_date": retrieved_at.isoformat(),
        "raw_source": str(raw_file),
        "rows": n_rows,
        "proj_crs": cfg.proj_crs,
    }
    # Trailing newline so the file is POSIX-clean and stable across re-runs (no
    # end-of-file-fixer churn on every rebuild).
    (processed / f"run_metadata_bridges_{cfg.iso}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )


COMMANDS = {
    "fetch": cmd_fetch,
    "build": cmd_build,
    "export": cmd_export,
    "viewer": cmd_viewer,
    "validate": cmd_validate,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bridges", description=__doc__)
    parser.add_argument("command", choices=list(COMMANDS), help="pipeline stage to run")
    parser.add_argument(
        "--country", default="NL", help="ISO country code (default: NL)"
    )
    parser.add_argument("--config", default=None, help="path to bridges.yml")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--interim-dir", default="data/interim")
    parser.add_argument("--processed-dir", default="data/processed")
    parser.add_argument(
        "--endpoint", default=None, help="Overpass endpoint (or 'mirror')"
    )
    parser.add_argument("--query-timeout", type=int, default=300)
    parser.add_argument("--read-timeout", type=int, default=360)
    parser.add_argument(
        "--source",
        choices=["overpass", "pbf"],
        default="overpass",
        help="extraction path: 'overpass' (API) or 'pbf' (offline Geofabrik, scales to all NL)",
    )
    parser.add_argument("--pbf", default=None, help="path to a specific .osm.pbf")
    parser.add_argument(
        "--bbox",
        default=None,
        help="restrict Overpass fetch/build to 'south,west,north,east' (WGS84) — fast testing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.endpoint is None:
        args.endpoint = osm.ENDPOINT
    elif args.endpoint == "mirror":
        args.endpoint = osm.MIRROR
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
