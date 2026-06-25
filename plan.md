# Bridges of the Netherlands — Data Pipeline Implementation Plan

**Goal:** Build a reproducible, free-to-run Python pipeline that extracts every bridge in the
Netherlands from OpenStreetMap, captures its physical and functional properties (type,
structure, movable mechanism, what it carries, span length, width, clearance, load/height
limits), and exports a clean dataset that drops straight into a Google Maps layer or any GIS.
Design every component so adding a new country is a config change, not a rewrite.

**Design principles**

1. **OpenStreetMap is the universal backbone.** It has the same bridge tags in every country,
   a free query API, and full geometry. Everything else is *optional enrichment* layered on top.
2. **Reproducible by construction.** Every external call is a version-controlled query or a
   dated snapshot. Raw responses are cached so transforms can be re-run offline and
   deterministically.
3. **One canonical schema, many export formats.** The internal model never changes; only the
   serializer differs per output product.
4. **Country-agnostic core + per-country config.** The Netherlands ships first; the same core
   produces a working dataset for any other country with a single YAML block.

A bridge is structurally simple to model: there is **no secondary feature to spatially join**
(a bridge *is* the feature), so extraction is a straight tag→schema mapping.

---

## 1. Architecture overview

```
                 ┌─────────────────────────────────────────────┐
                 │            EXTRACT  (per country)            │
                 │  A) Overpass API   (quick, iterative; bbox)  │
                 │  B) Geofabrik .pbf (dated, offline, scales)  │
                 └───────────────────────┬─────────────────────┘
                                         │  data/raw/  (bronze: dated JSON / .pbf)
                                         ▼
                 ┌─────────────────────────────────────────────┐
                 │   NORMALIZE → CLASSIFY → CANONICAL SCHEMA    │
                 │   • bridge ways + man_made=bridge structures │
                 │   • metric CRS for length/width              │
                 │   • carriageway / structure; movable flag    │
                 └───────────────────────┬─────────────────────┘
                                         │  data/interim/ (silver) · data/processed/ (gold)
                                         ▼
                 ┌─────────────────────────────────────────────┐
                 │   EXPORT                                     │
                 │   • GeoJSON  → Maps JS Data layer / Datasets │
                 │   • KML      → My Maps / Google Earth        │
                 │   • CSV+WKT  → My Maps / spreadsheets        │
                 └─────────────────────────────────────────────┘
```

The bronze/silver/gold layering is what makes the whole thing reproducible: re-running the
build never re-hits an API, and a result can always be traced back to a dated raw snapshot
recorded in `run_metadata_bridges_<C>.json`.

---

## 2. Why bridges, why OSM

- Bridges carry globally-consistent OSM tags (`bridge=*`, `man_made=bridge`,
  `bridge:structure=*`, `bridge:movable=*`), with full geometry and a free query API.
- For a water-advisory context the high-value attributes are the ones touching waterways:
  **movable bridges** (`bridge:movable=bascule|swing|lift|drawbridge` — they open for
  shipping), **aqueducts** (`bridge=aqueduct` — water *over* a road/rail), and **clearance
  height** (`maxheight`, `seamark:bridge:clearance_height`) which governs vessel passage.
- The Netherlands is densely and well mapped, so OSM coverage of bridges is high (≈ 125 k
  features at the current snapshot).

## 3. What counts as "a bridge"

A feature qualifies if **any** holds (recorded in `feature_kind` for auditing):

- **carriageway** — a way carrying a `bridge=*` tag other than `no` (the common case: the
  road / rail / cycleway / waterway segment that sits *on* the bridge). These carry the rich
  functional tags (`highway`/`railway`/`waterway`, `ref`, `layer`, `maxweight`, `maxheight`).
- **structure** — a way/area/relation tagged `man_made=bridge` (the physical bridge
  *outline*; less common in NL but gives a true footprint polygon when present).

Both are kept and labelled so a divided/duplicated mapping (an outline polygon *plus* the
carriageway way over it) can be grouped or de-duplicated downstream. Bridge-type vocabulary
captured from `bridge=*`: `yes`, `viaduct`, `aqueduct`, `boardwalk`, `cantilever`, `movable`,
`trestle`, `covered`, `low_water_crossing`, `simple_brunnel`.

---

## 4. Environment (Pixi)

Pixi/conda-forge is recommended over plain pip because the geospatial stack (GDAL, GEOS, PROJ
behind GeoPandas/pyosmium) installs cleanly from conda-forge and the `pixi.lock` file pins the
*exact* environment — a big reproducibility win. Key dependencies: `geopandas`, `shapely`,
`pyproj`, `pandas`, `requests`, `pyyaml`, `simplekml`, `osm2geojson` (Overpass JSON → GeoJSON),
`pyosmium` (offline `.pbf` parsing), `pydantic` (schema validation).

```toml
[tasks]
fetch    = "python -m bridges.pipeline fetch    --country NL --source pbf"
build    = "python -m bridges.pipeline build    --country NL --source pbf"
export   = "python -m bridges.pipeline export   --country NL"
validate = "python -m bridges.pipeline validate --country NL"
all      = { depends-on = ["fetch", "build", "export", "validate"] }
```

`simplekml` is preferred for KML over GeoPandas' KML driver, which is inconsistent across GDAL
builds.

---

## 5. Repository layout

```
bruggen-database/
├── pixi.toml / pixi.lock
├── README.md · LICENSE · ATTRIBUTION.md · CITATION.cff · DECISIONS.md
├── config/
│   └── bridges.yml                  # per-country: osm_area, geofabrik_url, proj_crs, regions
├── data/
│   ├── raw/        # bronze: dated Overpass JSON + .pbf snapshots
│   ├── interim/    # silver: classified bridge GeoJSON
│   └── processed/  # gold: final merged outputs (the deliverables)
├── src/bridges/
│   ├── config.py     # load bridges.yml
│   ├── osm.py        # low-level OSM access: Overpass constants, merge, to_gdf, .pbf helpers
│   ├── query.py      # bridge Overpass query builder + country/region fetch + cache
│   ├── extract.py    # classify carriageway/structure; Overpass + pyosmium paths
│   ├── schema.py     # canonical Bridge schema + validation
│   ├── export.py     # GeoJSON / KML / CSV writers
│   ├── validate.py   # QA report
│   └── pipeline.py   # CLI orchestration
└── test/             # network-free tests (synthetic geometries + tags)
```

Config-driven so a new country is a YAML block:

```yaml
# config/bridges.yml
NL:
  iso: NL
  osm_area: '["ISO3166-1"="NL"][admin_level=2]'
  geofabrik_url: https://download.geofabrik.de/europe/netherlands-latest.osm.pbf
  proj_crs: 28992   # Amersfoort / RD New — accurate spans/widths for NL
```

---

## 6. Phase 1 — Acquire

| Path | Tool | When |
|---|---|---|
| **A — Overpass API** | `bridges.osm` (POST + dated, content-hashed cache) | iterative dev, single bbox/region |
| **B — Geofabrik `.pbf`** | `bridges.osm.download_extract` + a pyosmium streamer | **the whole of NL** — a country-wide Overpass query for *every* bridge times out, so the national build streams `netherlands-latest.osm.pbf` |

Bridge Overpass query (generated from config):

```overpassql
[out:json][timeout:300];
area["ISO3166-1"="NL"][admin_level=2]->.cc;
(
  way["bridge"]["bridge"!="no"](area.cc);
  way["man_made"="bridge"](area.cc);
  relation["man_made"="bridge"](area.cc);
)->.b;
.b out geom;
```

Etiquette baked in: a descriptive `User-Agent`, a generous timeout, and idempotent caching so a
re-run never re-hits the public endpoint. Overpass reports a server-side timeout as a 200 with a
`remark` (not an HTTP error), so the fetcher raises on that instead of caching an empty result.

---

## 7. Phase 2 — Normalize & canonical schema

No spatial join. Convert Overpass JSON with `osm2geojson`, classify each feature
(`carriageway` vs `structure`), reproject to a metric CRS for length, and map tags to the
canonical record. **Project CRS for NL is EPSG:28992 (Amersfoort / RD New)** — the Dutch
national grid — for accurate span lengths; configurable per country (`proj_crs`, default 3035).

Canonical schema (`src/bridges/schema.py`):

| Field | Type | Source |
|---|---|---|
| `id` | str | OSM `type/id` (e.g. `way/12345`) |
| `group_id` | str | shared by all features of one physical bridge (see grouping below) |
| `group_size` | int | feature count in the group |
| `name` | str\|None | `name`, falling back to `bridge:name` |
| `country` | str | ISO 3166-1 alpha-2 |
| `lat`, `lon` | float | WGS84 centroid |
| `feature_kind` | str | `carriageway` / `structure` |
| `bridge_type` | str | value of `bridge=*` (or `structure`) |
| `structure` | str\|None | `bridge:structure` (arch, beam, suspension, …) |
| `movable` | str\|None | `bridge:movable` (bascule, swing, lift, …) |
| `is_movable` | bool | derived (`bridge=movable` or any `bridge:movable`) |
| `carries` | str\|None | what's on the bridge: `highway=*` / `railway=*` / `waterway=*` |
| `carries_type` | str\|None | `road` / `rail` / `water` / `foot` / `cycle` / `other` |
| `ref` | str\|None | road/route `ref` carried |
| `layer` | int\|None | OSM `layer` |
| `length_m` | float\|None | geodesic length of the way (or `length` tag) |
| `width_m` | float\|None | `width` |
| `maxweight_t`, `maxheight_m` | float\|None | parsed load / height limits |
| `material`, `operator`, `start_date` | str\|None | as tagged |
| `source` | str | `osm` |
| `osm_url` | str | `https://www.openstreetmap.org/{type}/{id}` |
| `data_retrieved_at` | date | OSM snapshot date |

A bridge need not have a name — most are unnamed — so naming is not a validation requirement.

**Grouping (`src/bridges/group.py`).** One physical bridge is mapped as many OSM features —
a long viaduct split into segments, the two carriageways of a divided road, a
`man_made=bridge` outline plus the way over it. After the schema mapping, features are linked
into connected components by three rules and each component gets a shared `group_id`:

1. **adjacent, same `carries_type`** — within `group_distance_m` (25 m). A missing
   `carries_type` is its own bucket, so a footbridge isn't merged with the car bridge beside it.
2. **same `carries_type`, same waterway** — within `group_water_distance_m` (80 m) and
   crossing the same river/canal/stream. This merges the two carriageways of a divided road over
   one body of water (requires extracting waterway centrelines and snapping each bridge to the
   waterway it sits on).
3. **same name** — within `group_name_distance_m` (60 m), *regardless of* `carries_type`, e.g.
   the road + cycle parts of the *Plantagebrug* in Delft.
4. **catch-all proximity** — within `group_merge_distance_m` (10 m), unconditionally; anything
   that close is the same structure.

Each group gets one representative point (`group_lat`/`group_lon`) **snapped onto the road**
(the midpoint of its longest carriageway), so the marker sits on the deck rather than drifting
into the water. For NL this collapses ≈ 125 k features to ≈ 75 k physical bridges. Features are
kept and tagged (not dissolved), so consumers can group or expand as needed.

---

## 8. Phase 3 — Export & Google Maps integration

**My Maps does not accept GeoJSON.** Produce all three formats so any consumption path works:

| Format | File | Consumes into |
|---|---|---|
| **GeoJSON** (RFC 7946) | `bridges_NL.geojson` | Maps **JavaScript API** Data layer; Maps **Datasets API**; GIS |
| **KML** | `bridges_NL.kml` | Google **My Maps**; Google **Earth** |
| **CSV + WKT** | `bridges_NL.csv` | Google **My Maps**; spreadsheets |

My Maps limits: ≤ 2,000 rows/layer, KML/KMZ ≤ 5 MB, CSV ≤ 40 MB; the geometry column must be
named `WKT`. A national bridge set is tens of thousands of rows, so the CSV/KML writers **warn**
(rather than fail) past the cap — split per province/type for My Maps; GeoJSON / the Datasets
API have no such cap.

---

## 9. Phase 4 — Validation & QA

Programmatic checks before publishing (`src/bridges/validate.py`): total count, geometry
validity (no empty/null), coordinates within the NL bbox, breakdowns by `bridge_type` /
`carries_type` / `feature_kind` / `bridge:structure`, and the **movable-bridge headline** (the
key figure for navigation use). Acceptance: geometries valid; every row inside the NL bbox; ≥ 1
export per format opens cleanly in its target product.

**Standing caveat (in the README):** OSM bridge tagging is incomplete and uneven, so this is a
*positive list* — "bridges known to OSM at the snapshot date", not an exhaustive register; and
attributes like clearance or load limit are present only where mappers added them.

---

## 10. Phase 5 — Automation & reproducibility

- **Orchestration:** `pixi run all` chains fetch → build → export → validate; the CLI takes
  `--country` and `--source`.
- **Scheduled refresh:** a monthly GitHub Action ([`.github/workflows/refresh.yml`](.github/workflows/refresh.yml))
  rebuilds via Path B and uploads the processed dataset as an artifact.
- **Data versioning:** raw snapshots are dated; the OSM snapshot date, source, row count and
  project CRS are recorded in `run_metadata_bridges_<C>.json`.
- **Determinism:** rows are sorted by `id` before writing, the env is pinned via `pixi.lock`,
  and all parameters live in `bridges.yml`, so a re-run on the same snapshot is byte-stable.

---

## 11. Expansion roadmap

The OSM core works for any country the moment a YAML block is added — `bridge=*` and
`man_made=bridge` are global tags. Per-country choices are limited to the project CRS (a
national grid for accurate spans) and, for large countries, splitting the Overpass fetch into
`regions`. Optional national enrichment (e.g. Rijkswaterstaat / Nationaal Wegenbestand
*kunstwerken* for official names, management authority, and exact clearances) can be matched to
OSM bridges by nearest-neighbour without touching the core.

---

## 12. Licensing & attribution

- **OSM is ODbL.** Any published map or derived dataset must show **"© OpenStreetMap
  contributors"**, and the share-alike clause can apply to a redistributed derived *database* —
  keep `ATTRIBUTION.md` and add the credit to the map UI.
- Verify each national source's licence as it is added; record all of them in one file.

---

## 13. Risks, limitations, mitigations

| Risk | Mitigation |
|---|---|
| OSM bridges under-/unevenly tagged | Treat output as a positive list, not a register; refresh monthly |
| Carriageway + structure double-mapping of one bridge | Keep both, labelled in `feature_kind`; expose a grouped "site" view later |
| Country-wide Overpass query times out | Use dated Geofabrik `.pbf` + pyosmium for the national build |
| Relations skipped (multipolygon bridges) | Documented omission; negligible in NL — revisit if a country maps bridges as relations at scale |
| Google My Maps row/size limits | Writers warn past the cap; split per province/type at national scale |
| GeoJSON rejected by My Maps | Always ship KML + CSV alongside GeoJSON |

---

## 14. Suggested milestones

1. **M1 — Skeleton + config:** `config/bridges.yml` (NL), `src/bridges/` package, bridge
   Overpass query; `fetch` caches raw OSM.
2. **M2 — Schema:** Overpass JSON → classified bridges → canonical gold GeoJSON for a bbox.
3. **M3 — Full NL via `.pbf`:** stream `netherlands-latest.osm.pbf`, national gold dataset.
4. **M4 — Exports + QA:** GeoJSON / KML / CSV; validation suite; movable-bridge headline.
5. **M5 — Enrichment (optional):** Rijkswaterstaat / NWB bridge & *kunstwerken* open data for
   official names, management authority, exact clearances.
