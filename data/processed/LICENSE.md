# Data licence & attribution — bridges database

**Disclaimer of ownership.** The datasets in this folder (`bridges_*.geojson` / `.kml` /
`.csv` and the `*.gold.geojson` intermediates) are **derived works**. The author/publisher
of this repository does **not own** the underlying geographic data and makes **no ownership
claim** over it. This project merely **processes, filters, and reformats** openly licensed
source data into a convenient form. All rights and obligations remain with the original data
provider below.

---

## Primary source — OpenStreetMap (ODbL)

The locations, names, and tags originate from **OpenStreetMap**.

> **© OpenStreetMap contributors**

- Licence: **Open Database License (ODbL) v1.0** — <https://opendatacommons.org/licenses/odbl/1-0/>
- The ODbL is **share-alike**: if you publicly use or redistribute this derived database,
  you must keep the **"© OpenStreetMap contributors"** attribution and license any
  redistributed derived database under compatible terms.
- When displayed on a map, the credit must be visible in the map UI.

---

## What this dataset is (and is not)

- It is a **positive list**: bridges **known to OpenStreetMap** at the snapshot date recorded
  in `run_metadata_bridges_*.json`.
- **Coverage and attributes are uneven** — OSM bridge tagging is incomplete, so a bridge may
  be missing, or present but lacking properties such as clearance, width, or load limit that
  simply aren't mapped yet.
- `feature_kind` distinguishes a `carriageway` (the way carrying a `bridge=*` tag) from a
  `structure` (`man_made=bridge` outline); a single physical bridge can appear as both.

See the repository's top-level [`ATTRIBUTION.md`](../../ATTRIBUTION.md) for the full source
list and the project [`LICENSE`](../../LICENSE) (GNU GPL-3) covering the code.
