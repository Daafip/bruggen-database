# Bruggen database

Build a clean, reproducible **database of bridges in the Netherlands** with their
properties — type, structure, movable mechanism, what they carry, span length, clearance,
load/height limits — straight from OpenStreetMap, and export it as GeoJSON / KML / CSV that
drops into a Google Maps layer or any GIS. Adding a country is a config change, not a
rewrite.

OpenStreetMap is the universal backbone (same tags everywhere, free API, full geometry).
The pipeline is **reproducible by construction**: every external call is a
version-controlled query or a dated, cached snapshot, so transforms re-run offline and
deterministically.

> **Caveat:** OSM bridge tagging is incomplete and uneven, so this is a *positive list* —
> "bridges known to OSM at the snapshot date", not an exhaustive register. Attributes such
> as clearance or load limit are present only where mappers added them.

## How it works

```text
EXTRACT (per country)        NORMALIZE → CLASSIFY → SCHEMA        EXPORT
  OSM via Overpass (A)   →    bridge ways + structures        →   GeoJSON  (Maps JS / Datasets / GIS)
  OSM via Geofabrik (B)       metric CRS, carriageway/structure    KML      (My Maps / Earth)
                              canonical schema, sort by id         CSV+WKT  (My Maps / sheets)
   └ data/raw (bronze)         └ data/interim (silver)              └ data/processed (gold)
```

The bronze/silver/gold layering is what makes it reproducible: re-running the build never
re-hits an API, and any output traces back to a dated raw snapshot recorded in
`run_metadata_bridges_<country>.json`.

A bridge is captured under one of two kinds, recorded in `feature_kind`: `carriageway`
(a way carrying a `bridge=*` tag — the road/rail/cycleway/waterway *on* the bridge, holding
the functional tags) or `structure` (a `man_made=bridge` outline). Movable bridges
(`bridge:movable=bascule|swing|lift|drawbridge`) and aqueducts (`bridge=aqueduct`) — the
features that matter for waterway navigation — are flagged explicitly.

**Grouping.** One physical bridge is often mapped as several OSM features (a long viaduct
split into segments, the two carriageways of a divided road, a `man_made=bridge` outline plus
the way over it). The build assigns a shared `group_id` by linking features under three rules:
(1) adjacent and **same `carries_type`**; (2) **same `carries_type` crossing the same waterway**
within a wider distance — so the two carriageways of a divided road over one canal/river merge;
(3) near and the **same name**, regardless of type — so the road + cycle parts of a named bridge
(e.g. the *Plantagebrug* in Delft) merge. A footbridge is never merged with the car bridge
beside it unless they share a name. For NL this collapses ≈ 125 k features into ≈ 93 k physical
bridges; the map shows one marker per group. All three distances are per-country config.

## Usage

```bash
pixi install                       # installs the geospatial stack from conda-forge

# Whole of NL: use Path B (pyosmium streams the Geofabrik .pbf). A single Overpass query
# for an entire country times out, so --source pbf is the reliable route.
pixi run python -m bridges.pipeline fetch    --country NL --source pbf   # ~1.3 GB download
pixi run python -m bridges.pipeline build    --country NL --source pbf   # parse + classify + schema
pixi run python -m bridges.pipeline export   --country NL
pixi run python -m bridges.pipeline viewer   --country NL   # lightweight Leaflet HTML map
pixi run python -m bridges.pipeline validate --country NL

# Iterative / small-area work: the Overpass API path, restricted to a bounding box:
pixi run python -m bridges.pipeline fetch --country NL --bbox 52.150,4.470,52.175,4.505
pixi run python -m bridges.pipeline build --country NL --bbox 52.150,4.470,52.175,4.505
```

`pixi run all` chains fetch → build → export → viewer → validate (Path B) for NL. Outputs
land in `data/processed/`: `bridges_<C>.geojson` / `.kml` / `.csv` (+
`run_metadata_bridges_<C>.json`).

### Preview the data

The full GeoJSON is too large for Google's preview, so `viewer` renders a **single,
lightweight HTML map** (`bridges_<C>_viewer.html`, a few MB) you can open straight in a
browser: one marker per physical bridge (grouped) in a client-side cluster, plus the
movable bridges as colour-coded markers with popups. The data is embedded in the file;
Leaflet and the map tiles load from
their usual CDN/tile servers (so it needs internet to *render*, like any web map).

```bash
pixi run viewer && xdg-open data/processed/bridges_NL_viewer.html
```

**Extraction paths**: `--source overpass` (default) hits the Overpass API — quick and
download-free, best with `--bbox` for a small area; `--source pbf` parses a dated Geofabrik
`.osm.pbf` with pyosmium — offline, no rate limits, and the only practical route for a whole
country.

### Adding a country

Add a block to [`config/bridges.yml`](config/bridges.yml) — the OSM core works immediately.
The only NL-specific choice is `proj_crs: 28992` (Amersfoort / RD New) for accurate span
lengths; other countries can use the pan-European default (EPSG:3035) or their own grid.

## Consuming in Google products

**My Maps does not accept GeoJSON**, so all three formats are produced. My Maps limits:
≤ 2,000 rows/layer, KML/KMZ ≤ 5 MB, CSV ≤ 40 MB (geometry column must be named `WKT`).
A national bridge set is tens of thousands of rows, so split it per province/type for My
Maps — GeoJSON / the Datasets API have no such cap.

- **My Maps (no code):** New layer → Import → upload a (split) **KML** or **CSV** → style by
  `bridge_type` or `carries_type`.
- **Maps JavaScript API:** host the GeoJSON (e.g. GitHub Pages) and
  `map.data.loadGeoJson('…/bridges_NL.geojson')`.
- **Datasets API:** upload the same GeoJSON as a dataset and reference its ID in a
  data-driven layer.

## Licensing

Data is derived from OpenStreetMap (**ODbL** — "© OpenStreetMap contributors", share-alike
may apply). See [ATTRIBUTION.md](ATTRIBUTION.md) before publishing.

## Development with Pixi

The environment is managed with [Pixi](https://pixi.sh); `pixi.lock` pins the exact
geospatial stack (GDAL/GEOS/PROJ via conda-forge) for reproducibility.

<details>
<summary>Install Pixi</summary>

```bash
# Linux/Mac
curl -fsSL https://pixi.sh/install.sh | bash
# Windows (PowerShell)
iwr -useb https://pixi.sh/install.ps1 | iex
```

</details>

```bash
pixi install        # create the environment from pixi.lock
pixi run test       # run the test suite (pytest)
pixi run pre-commit # lint/format via pre-commit
```

This bruggen-database is developed by David Haasnoot, based heavily on other open source
projects, and is published under the GNU GPL-3 license.
