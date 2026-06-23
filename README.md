# Speeltuinen langs de snelweg — rest stops with playgrounds

Find highway rest stops that have a playground and export them as a clean dataset that
drops straight into a Google Maps layer. Germany ships first; adding a country is a
config change, not a rewrite.

OpenStreetMap is the universal backbone (same tags everywhere, free API, full geometry);
national sources such as the **Autobahn GmbH API** are optional enrichment layered on
top. The pipeline is **reproducible by construction**: every external call is a
version-controlled query or a dated, cached snapshot, so transforms re-run offline and
deterministically.

> **Caveat:** OSM playground tagging is incomplete, so *absence of a playground is not
> proof there is none*. This dataset is "known to have a playground per current OSM /
> official data," not an exhaustive negative.

## How it works

```text
EXTRACT (per country)        NORMALIZE → JOIN → ENRICH       MERGE → SCHEMA        EXPORT
  OSM via Overpass (A)   →    rest areas + playgrounds   →   canonical schema  →   GeoJSON  (Maps JS / Datasets)
  OSM via Geofabrik (B)       metric CRS, buffer, sjoin      dedup, sort by id      KML      (My Maps / Earth)
  DE: Autobahn GmbH API       has_playground / match_type                           CSV+WKT  (My Maps / sheets)
   └ data/raw (bronze)         └ data/interim (silver)         └ data/processed (gold) ─┘
```

The bronze/silver/gold layering is what makes it reproducible: re-running the join or
changing a buffer radius never re-hits an API, and any output traces back to a dated raw
snapshot recorded in `run_metadata_<country>.json`.

A rest stop qualifies via one of three rules, recorded in `match_type` for later QA:
`tag` (the stop carries `playground=yes`), `contained` (a playground polygon falls inside
an area-mapped stop), or `proximity` (a playground lies within a buffer of a point-mapped
stop — the common case).

## Usage

```bash
pixi install                       # installs the geospatial stack from conda-forge

# Germany: use Path B (pyosmium streams the Geofabrik .pbf). A single Overpass query
# for a whole large country times out, so --source pbf is the reliable route.
pixi run python -m restspots.pipeline fetch    --country DE --source pbf   # ~4.8 GB download
pixi run python -m restspots.pipeline build    --country DE --source pbf   # parse + join + enrich
pixi run python -m restspots.pipeline export   --country DE
pixi run python -m restspots.pipeline validate --country DE

# Small countries: the Overpass API path (the default) works fine, no download:
pixi run python -m restspots.pipeline fetch    --country NL
pixi run python -m restspots.pipeline build    --country NL
```

`pixi run all` chains fetch → build → export → validate (Overpass path) for the default
country. Outputs land in `data/processed/`:
`rest_stops_playgrounds_<C>.geojson` / `.kml` / `.csv` (+ `run_metadata_<C>.json`).

**Extraction paths**: `--source overpass` (default) hits the Overpass API — quick and
download-free, best for small/medium areas; `--source pbf` parses a dated Geofabrik
`.osm.pbf` with pyosmium — offline, no rate limits, and the only practical route for a
country the size of Germany.

### Adding a country

Add a block to [`config/countries.yml`](config/countries.yml) — the OSM core works
immediately. National enrichment connectors live in
[`src/restspots/enrich/`](src/restspots/enrich/) and implement one tiny interface
(`fetch → raw`, `to_points → GeoDataFrame[name, ref, geometry]`), matched to OSM stops by
nearest neighbour.

## Consuming in Google products

**My Maps does not accept GeoJSON**, so all three formats are produced. My Maps limits:
≤ 2,000 rows/layer, KML/KMZ ≤ 5 MB, CSV ≤ 40 MB (geometry column must be named `WKT`).

- **My Maps (no code):** New layer → Import → upload the **KML** or **CSV** → style by
  `feature_type` or `motorway_ref`.
- **Maps JavaScript API:** host the GeoJSON (e.g. GitHub Pages) and
  `map.data.loadGeoJson('…/rest_stops_playgrounds_DE.geojson')`.
- **Datasets API:** upload the same GeoJSON as a dataset and reference its ID in a
  data-driven layer.

## Licensing

Data is derived from OpenStreetMap (**ODbL** — "© OpenStreetMap contributors", share-alike
may apply) and national open data. See [ATTRIBUTION.md](ATTRIBUTION.md) before publishing.

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

This Speeltuinen langs de snelweg is developed by David Haasnoot, based heavily on other
open source projects, and is published under the GNU GPL-3 license.
