# 🇬🇧 UK Playground Recall — Improvement Plan

**Why this exists:** the current OSM-only pipeline under-counts UK rest stops with play facilities.
This extends the UK section of the expansion plan with a recall-improvement strategy. The headline:
**OSM recall alone will never fix the UK** — the country needs an *enumerate-then-verify* approach
built on authoritative facility data, because the dominant UK play format is invisible to the OSM
spatial join.

---

## 1. What the map is actually showing — two different problems

The two circled corridors fail for opposite reasons. Treating them the same would waste effort.

**West (M5 / Somerset) — mostly a DATA gap → recoverable.**
The M5 is one of the busiest family corridors in the country and several of its services *do* have
play areas that the OSM join is missing — Gloucester (Westmorland: indoor **and** outdoor play, lake
and duck pond), plus likely Sedgemoor and Taunton Deane, and Cornwall Services down on the A30
(indoor soft play). These exist in reality but aren't tagged `leisure=playground` in OSM, so they
never enter the dataset. **This circle is where enrichment recovers real locations.**

**Southeast (M20 / Kent) — mostly REAL sparsity → mostly not a data gap.**
Kent genuinely has very few services: the M20 has only **Maidstone (J8)** and **Folkestone (J11)**,
with **Medway** on the parallel M2. The M20 was built in 1991 with no service areas at all, and
Maidstone (Roadchef) today is McDonald's / Costa / Esso / WHSmith / hotel — **no play area**. So the
honest answer for this circle is *not* "we missed playgrounds" but "there are barely any services,
and the ones there have none." **The win here is scope expansion** (near-junction family stops —
Leeds Castle sits right by M20 J8), not OSM recall. §6 covers this.

**The continent looks dense by contrast** because German/French play areas are better tagged in OSM
*and* the motorway network has more, larger service areas — so the UK sparsity is real *and*
exaggerated by tagging differences.

---

## 2. Why OSM under-counts UK play facilities (root causes)

| Cause | Effect | Fix |
|---|---|---|
| **Indoor soft play ≠ `leisure=playground`** — the dominant UK format at services is *indoor* soft play (Moto's Leigh Delamere West & Donington; Cornwall Services), which OSM doesn't tag as a playground | The spatial join **never sees** the most common UK play facility | Use authoritative facility data (§3); add a `play_type` field for indoor/outdoor |
| **OSM under-tagging** of even outdoor play areas (the §9 standing caveat) | Real outdoor playgrounds missing from OSM entirely | Cross-check authoritative sources; don't treat OSM absence as proof |
| **Best UK family stops are often *just off* the junction** (farm shops, country parks, NT, pubs) | They fall outside any `highway=services` polygon and the proximity buffer | Optional near-junction expansion (§6) |
| **Volatility** — play areas are no longer a required facility (since 2022) and are often removed early | Any snapshot goes stale in both directions | `last_verified` dating + quarterly UK refresh (§7) |

---

## 3. The fix — authoritative enrichment + verification (not OSM recall)

The UK universe is **small and well-documented** (~130 motorway + major A-road services), so
enumerate-then-verify is tractable: list every service on a road, then confirm play facilities from
sources that actually record them.

| Tier | Source | Provides | Why it matters |
|---|---|---|---|
| **1 — primary** | **Motorway Services Online** (`motorwayservices.uk`) | Database of **every** service area; a **search filter for play areas** (by road, indoor vs outdoor, side-of-road), and **per-road KML export** for Google Earth / sat-navs | The single best UK source — queryable, side-aware, and its KML drops straight into the existing pipeline / My Maps |
| **2 — confirm/freshen** | **Operator facility pages** — Moto, Welcome Break, RoadChef, Extra, Westmorland | Per-location amenities incl. play areas; Extra sites "all have playgrounds"; Westmorland (Tebay, Gloucester, Cairn Lodge, Killington Lake, Gretna) have indoor + outdoor play | Authoritative for currency and for `play_type` / indoor-outdoor |
| **3 — tie-break** | **Google Places** per enumerated site | Reviews / photos / attributes mentioning "play area" / "soft play" | Independent confirmation + freshness |
| **4 — keep, broaden** | **OSM** widened matching | `leisure=playground` **plus** `playground=*` on the parent feature, and indoor-play tags (`leisure=indoor_play` etc.) where present | Still useful; just no longer the sole signal |

**Reconciliation rule:** a stop is `has_playground = True` if **any** tier confirms it. Record which
tier(s) confirmed (provenance), and prefer authoritative (MSO / operator) names and coordinates over
OSM when a match is found.

> **Quick win — do this today, no code:** run a per-road play-area search on Motorway Services
> Online for each road on your route (M5, M4, M3, M20, M2…), download each road's **KML**, and import
> them as extra layers in My Maps. That alone will populate the western (M5) circle immediately,
> ahead of building the connector below.

---

## 4. Schema & pipeline changes (concrete)

**New / changed fields:**

| Field | Type | Notes |
|---|---|---|
| `play_type` | str | `outdoor` / `indoor_soft_play` / `both` / `unknown` |
| `side` | str | `both` / `NB` / `SB` / `single` — many UK play areas are one-direction only |
| `stop_class` | str | `motorway_services` / `a_road_services` / `near_junction` (§6) |
| `verified_source` | list | any of `osm` / `mso` / `operator` / `places` |
| `last_verified` | date | drives the staleness downgrade (§7) |

**Extend the `match_type` enum** (from §6 of the main plan) with authoritative, *non-spatial*
confirmations: add `mso_listed` and `operator_listed` alongside `tag` / `contained` / `proximity`.
This lets a stop qualify on a trusted facility listing even when no playground geometry exists in OSM
— which is exactly the indoor-soft-play case.

**UK connector** — same tiny interface as every other country connector:

```python
# src/restspots/enrich/uk.py
def fetch(country="GB") -> dict:
    # Tier 1: per-road MSO play-area search + KML; Tier 2: operator pages; Tier 3: Places
    # cache every response under data/raw/ with a date stamp, exactly like the Autobahn connector
    ...

def to_points(raw) -> "GeoDataFrame":
    # columns: name, ref, side, play_type, verified_source, geometry
    ...
```

Matched to OSM stops by nearest + road `ref`. The `ref_road_tags: [motorway, trunk]` toggle from the
expansion plan matters here — UK services sit on trunk A-roads too, not only motorways.

---

## 5. Corridor audit — turning "find more" into a checklist

Since you're auditing specific routes (M5 → M3/M4 → M20), add a task that takes a road list and
emits *candidates to add / to verify*:

```python
# pixi run audit --roads M5,M4,M3,M20,M2
def corridor_audit(roads: list[str], current_gdf):
    mso = fetch_mso_playareas(roads)          # Tier 1, per road
    have = current_gdf[current_gdf.motorway_ref.isin(roads)]
    # nearest-match mso ↔ have; anything in mso not matched in `have` is a candidate
    return {
        "to_add":     mso_unmatched,           # confirmed play area, missing from dataset
        "to_verify":  proximity_only_matches,  # OSM proximity hits to eyeball
        "side_check": single_side_sites,       # one-direction-only play areas
    }
```

Output is a per-corridor list you can sanity-check against the map before importing — the workflow
you're already doing by hand, automated.

---

## 6. Optional scope expansion — near-junction family stops (fixes Kent)

For corridors that are genuinely sparse, broaden beyond on-motorway services to family stops within
~3–5 km of a junction. This is how UK families actually break journeys, and it's the only thing that
will put pins in the M20/Kent circle.

- **Sources:** JustOffJunction (has a dedicated play-areas-off-junctions page), OSM near junctions
  (`leisure=playground`, `leisure=park`, `shop=farm`, `tourism=*`), Google Places.
- **Tag distinctly** with `stop_class = near_junction` so these never get confused with true service
  areas in the canonical dataset, and gate them behind a config toggle so the "pure motorway" product
  stays clean.
- **Kent examples to seed:** Leeds Castle (M20 J8), country parks and farm-shop cafés off J8/J7.

---

## 7. Currency & refresh

Play areas get added and removed, so a stale "yes" is worse than an honest "unknown":

- Stamp every confirmation with `last_verified`; **downgrade `has_playground` to "unverified"** if the
  newest confirmation is older than ~6 months.
- Re-run the **UK connector quarterly** (more often than the monthly OSM refresh), since operator/MSO
  data changes faster than OSM tags.
- Watch status changes — e.g. the derelict **Aust services (M48)** is being converted into a soft-play
  centre (Gympanzees), expected to open around 2026 — exactly the kind of change a quarterly re-scrape
  catches.

---

## 8. Licensing & etiquette

- **Motorway Services Online** and **JustOffJunction** are independent/hobbyist sites — **cache,
  attribute, throttle, don't hammer**, and check their terms before *redistributing* their data
  (their KML is aimed at personal sat-nav use). Safest pattern: use MSO as a **discovery + verification**
  source, then re-derive published coordinates from OSM / Places where you can, or seek permission.
- **Operator data** © the respective operators — fine for verification, confirm before bulk reuse.
- **Google Places** under its API terms (don't store beyond what's permitted).
- **OSM** remains **ODbL** — "© OpenStreetMap contributors" as before.

---

## 9. Expected recoveries (so this isn't abstract)

**Likely to come back on the M5 / west circle** (verify each via MSO/operator):

- **Gloucester** (M5, Westmorland) — indoor **and** outdoor play, lake — *documented*.
- **Cornwall Services** (A30) — indoor soft play — *documented*.
- **Sedgemoor**, **Taunton Deane** (M5) — *check MSO play-area filter*.

**Elsewhere on your route / nearby:**

- **Leigh Delamere West** (M4, Moto) — indoor play — *documented*.
- **Donington Park** (M1, Moto) — indoor play — *documented*.
- **Chieveley** (M4/A34) — indoor play area — *listed*.
- **Extra** chain sites — *play areas across the chain*.

**Honest note for the M20 / Kent circle:** expect little. **Maidstone** has no play area; **Folkestone
(Stop 24, J11)** and **Medway (M2, Moto)** need checking but the corridor is thin. The realistic
answer for Kent is the near-junction expansion in §6, not motorway services.

---

## 10. Mini-roadmap

1. **Today:** per-road MSO play-area search → KML → import as My Maps layers (populates the M5 circle).
2. **Phase 1:** add the schema fields + `mso_listed` / `operator_listed` match types; build the UK
   connector (Tier 1 MSO, Tier 2 operators).
3. **Phase 2:** add Tier 3 Places confirmation + the corridor-audit task.
4. **Phase 3:** optional near-junction expansion (`stop_class=near_junction`) for sparse corridors.
5. **Standing:** quarterly UK refresh + `last_verified` staleness downgrade.

---

## References

- Motorway Services Online — `https://motorwayservices.uk/` (per-road search, play-area filter, KML export)
- JustOffJunction — `https://www.justoffjunction.co.uk/playareas.php`
- Operators — Moto `moto-way.com` · Welcome Break `welcomebreak.co.uk` · RoadChef `roadchef.com` · Extra `extraservices.co.uk` · Westmorland `westmorland.com`
- (Carried from the expansion plan) National Highways Open Data — `https://opendata.nationalhighways.co.uk/`
