# Decisions, Improvements & Outlook

Companion to [`plan.md`](plan.md). Records *what was actually built and why* — especially where
reality diverged from the plan — plus what to watch next.

**Status:** OSM-only core shipped for the **Netherlands**, validating. Current snapshot:

| metric | value |
|---|---|
| OSM features | **125,183** (101,444 carriageway · 23,739 structure) |
| physical bridges (grouped) | **75,099** (shared `group_id`; see D10) |
| movable | **2,566** — 1,235 bascule · 271 swing · 220 drawbridge · 145 lift · … |
| aqueducts | 64 |
| with span length | 99,906 (computed in EPSG:28992 / RD New) |
| carries | 42,843 road · 36,226 foot · 15,555 cycle · 5,015 rail · 83 water |

Exported to GeoJSON / KML / CSV in [`data/processed/`](data/processed/) with
`run_metadata_bridges_NL.json` for provenance.

---

## Decisions

ADR-style: each is *context → decision → why*. Numbered for reference.

### D1 — A bridge IS the feature: no spatial join
This project started as a reuse of a rest-stops-with-playgrounds pipeline, which spatially
joined two feature types (stops × playgrounds). A bridge has no secondary feature to join, so
that whole phase **collapsed into a straight tag→schema mapping**. The shared low-level OSM
access (Overpass fetch + cache, `osm2geojson` conversion, pyosmium `.pbf` streaming) was kept;
the join/enrichment machinery was dropped. The package is now self-contained
([`src/bridges/`](src/bridges/)) with no dependency on the original code.

### D2 — Relations are skipped
`extract.from_pbf` captures nodes and ways only — assembling `man_made=bridge` multipolygon
relations is not worth the complexity for a negligible count. Documented as a known omission.

### D3 — Extraction path: Path B (`.pbf`) is the default for a whole country
A single Overpass query for *every* bridge in NL times out (the public API returns a 200 with a
`remark: "Query timed out"`). **Decision: Path B (dated Geofabrik `.pbf` + pyosmium) is the
reliable national route;** Overpass (Path A) stays the default only for small/iterative use,
where `--bbox` restricts it to a manageable area. The CI workflow uses `--source pbf`.

### D4 — pyosmium streaming, not a materialising parser
The `.pbf` is streamed with **pyosmium**, which keeps a compact node-location index and filters
tags in C++ (`osmium.filter.KeyFilter("bridge", "man_made")`), so only bridge features reach
Python. The 1.3 GB Netherlands extract parses in one pass at bounded memory. See
[`src/bridges/extract.py`](src/bridges/extract.py) and [`osm.py`](src/bridges/osm.py).

### D5 — Project CRS is the national grid (EPSG:28992 for NL)
Span `length_m` is computed from the way geometry, so CRS choice affects accuracy. NL uses
**EPSG:28992 (Amersfoort / RD New)** rather than the pan-European LAEA default (EPSG:3035),
which distorts distances slightly. `proj_crs` is a per-country config field.

### D6 — Two feature kinds, both kept
`carriageway` (a way tagged `bridge=*`) carries the functional attributes; `structure`
(`man_made=bridge`) gives a footprint. A single physical bridge can appear as both. They are
**kept and labelled in `feature_kind`** rather than de-duplicated, so the choice is the
consumer's. Length is computed only for line-mapped features (a polygon perimeter is not a span).

### D7 — Name is not a validation requirement
Most bridges are unnamed in OSM, so — unlike the rest-stops lineage, where every row needed a
name or ref — the bridge validator does **not** require a name. `name` falls back to
`bridge:name` and is otherwise left null.

### D8 — Measurement tags are parsed leniently
`width`, `maxweight`, `maxheight` are free-text in OSM (`"4.2 m"`, `"30 t"`). A small regex
extracts the leading number into typed `width_m` / `maxweight_t` / `maxheight_m`. Coverage is
sparse (these tags are rarely mapped) — that is OSM reality, surfaced honestly, not a defect.

### D9 — Exporters warn, not fail, past the My Maps cap
A national bridge set is tens of thousands of rows — far past the My Maps 2,000-row layer cap.
The full database is a legitimate deliverable, so the CSV/KML writers **warn** and write the
file anyway (the original rest-stops exporter hard-failed). Split per province/type only when
loading into My Maps; GeoJSON / the Datasets API have no cap.

### D10 — Grouping is connected components over four rules, with a different-name guard
One physical bridge is mapped as many OSM features (viaduct segments, divided-road
carriageways, structure outline + carriageway). **Decision: build a graph where two features
are linked by any of four rules, then take connected components → `group_id`** (see
[`src/bridges/group.py`](src/bridges/group.py)):

1. **adjacent same kind** — within `group_distance_m` (25 m) *and* equal `carries_type`
   (split segments / touching carriageways). Missing `carries_type` is its own bucket.
2. **same crossing** — within `group_water_distance_m` (80 m), equal `carries_type`, and
   crossing the **same waterway**. The divided-road case: the two carriageways over one
   canal/river merge even when tens of metres apart. Requires extracting river/canal/stream
   centrelines (`bridges.extract`) and snapping each bridge to the waterway it sits on
   (`sjoin_nearest`, ≤ 8 m).
3. **same name** — within `group_name_distance_m` (60 m) and an equal case-folded `name`,
   *regardless of* `carries_type`. Collapses the road + cycle parts of a named bridge, e.g.
   the **Plantagebrug** in Delft (verified: its features land in one group).
4. **catch-all proximity** — within `group_merge_distance_m` (10 m). Merges leftover outlines
   and near-duplicate mappings rules 1–3 miss.

**Different-name guard.** Rules 1, 2 and 4 never merge two features that *both* carry a name
and the names differ. Without it, the 10 m catch-all swallowed three distinct named bridges a
few metres apart along a Delft canal (Plantagebrug / Tweemolentjesbrug / Duyvelsgatbrug) into
one — the user spotted two "removed". The guard keeps differently-named bridges separate while
still letting an *unnamed* segment or outline join its named bridge. Verified: the three Delft
bridges are now three groups.

**Representative point.** Each group gets one `group_lat`/`group_lon` = the **mean of its
members' centroids**. (An earlier version snapped this onto the longest carriageway midpoint;
that was reverted — on a mis-merged group it placed the marker confusingly far from the named
bridge, and once merges are correct the plain mean is clear enough. Re-introducing carriageway
snapping is a one-function change if wanted.)

Result for NL: 125,183 features → **78,646** physical bridges. Rules 1–3 cross `carries_type`
only via the name rule; rule 4 is type-agnostic but tiny (10 m) and name-guarded. `group_id` is
numbered by the smallest member OSM id (deterministic). Features are kept (not dissolved) and
tagged with `group_id` / `group_size` / `group_lat` / `group_lon`; the map shows one marker per
group. All four distances are per-country config — genuinely distinct *unnamed* bridges that
sit within them will still merge, an accepted, tunable trade-off.

---

## Outlook / watch-list

Ordered roughly by value. Nothing here is required for the current deliverable.

1. **Rijkswaterstaat / NWB enrichment.** The Nationaal Wegenbestand and RWS *kunstwerken* open
   data could attach official names, the managing authority, and exact clearances — matched to
   OSM bridges by nearest-neighbour, without touching the core. The single highest-value add for
   a water-advisory context.
2. **Over-water detection.** "Bridge over a waterway" currently relies on tags (`bridge=aqueduct`,
   `waterway=*` on the way). True crossing detection (intersecting the bridge with the waterway
   layer below) would let clearance-over-water be reasoned about directly.
3. **Carriageway/structure grouping.** A grouped "site" view that links the structure outline to
   the carriageway(s) over it would de-duplicate the physical-bridge count for reporting.
4. **`.pbf` snapshot dating.** Geofabrik's `-latest` URL is mutable; `run_metadata` records the
   download date, but storing the dated filename would make provenance exact.
5. **Other countries.** A new country is a YAML block (`osm_area`, `geofabrik_url`, `proj_crs`,
   and `regions` for splitting a large Overpass fetch).

### Standing caveat
**OSM bridge tagging is incomplete and uneven.** This is a *positive list* — "bridges known to
OSM at the snapshot date" — not an exhaustive register, and attributes like clearance or load
limit are present only where mappers added them. Refresh monthly.
