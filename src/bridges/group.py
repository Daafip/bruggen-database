"""Group OSM features that belong to the same physical bridge.

One real bridge is often mapped as several OSM features: a long viaduct split into
segments, the two carriageways of a divided road, or a ``man_made=bridge`` outline plus the
``bridge=*`` way over it. Left ungrouped, the dataset double-counts and the map shows a
cluster of pins where there is one bridge.

Features are linked into connected components by three rules; any link merges them:

1. **same kind, adjacent** — within ``distance_m`` and equal ``carries_type``
   (split segments / touching carriageways). A missing ``carries_type`` is its own bucket,
   so a bare structure outline never bridges two real types.
2. **same crossing** — within ``water_distance_m``, equal ``carries_type``, and crossing the
   **same waterway** (``water_id``). This is the divided-road case: the two carriageways over
   one canal/river become a single bridge even when they sit tens of metres apart.
3. **same name** — within ``name_distance_m`` and an equal (case-folded) ``name``, *regardless
   of* ``carries_type``. This collapses the road + cycle parts of a named bridge (e.g. the
   "Plantagebrug" in Delft) that rule 1 would keep apart.

``group_id`` is deterministic (groups numbered by their smallest member OSM id), so a re-run
on the same snapshot is byte-stable.
"""

from __future__ import annotations

from collections import defaultdict

import geopandas as gpd
import pandas as pd

_NO_TYPE = "__none__"  # so a missing carries_type groups only with itself, not NaN!=NaN
_WATER_SNAP_M = 8.0  # a bridge is "over" a waterway if within this many metres of it


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _norm_name(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split()).casefold()


def _pairs(sub: gpd.GeoDataFrame, distance: float):
    """Yield index pairs (i, j) with i < j for features within ``distance`` of each other."""
    if not len(sub):
        return
    joined = gpd.sjoin(sub, sub, predicate="dwithin", distance=distance)
    for li, ri in zip(joined.index, joined["index_right"]):
        if li < ri:
            yield int(li), int(ri)


def assign_groups(
    gdf: gpd.GeoDataFrame,
    waterways: gpd.GeoDataFrame | None = None,
    distance_m: float = 25.0,
    water_distance_m: float = 80.0,
    name_distance_m: float = 60.0,
    crs: int = 28992,
    country: str = "NL",
) -> gpd.GeoDataFrame:
    """Return ``gdf`` with ``group_id`` and ``group_size`` columns.

    See the module docstring for the three linking rules. ``waterways`` (``[water_id,
    geometry]``) enables rule 2; if it is None/empty that rule is simply skipped. The input
    is returned unchanged in order and geometry.
    """
    out = gdf.copy()
    n = len(out)
    if n == 0:
        out["group_id"] = []
        out["group_size"] = []
        return out

    g = out.to_crs(crs).reset_index(drop=True)
    ct = (
        g["carries_type"].fillna(_NO_TYPE).to_numpy()
        if "carries_type" in g.columns
        else [_NO_TYPE] * n
    )
    names = [_norm_name(v) for v in (g["name"] if "name" in g.columns else [None] * n)]
    orig_id = out["id"].to_numpy()  # positional, matches g
    valid = (g.geometry.notna() & ~g.geometry.is_empty).to_numpy()

    water_id = _assign_water(g, waterways, crs) if waterways is not None else [None] * n

    uf = _UnionFind(n)

    # Rule 1 — adjacent, same carries_type.
    for li, ri in _pairs(g.loc[valid, ["geometry"]], distance_m):
        if ct[li] == ct[ri]:
            uf.union(li, ri)

    # Rule 2 — same carries_type crossing the same waterway (divided-road carriageways).
    has_water = valid & pd.notna(pd.array(water_id, dtype="object"))
    for li, ri in _pairs(g.loc[has_water, ["geometry"]], water_distance_m):
        if ct[li] == ct[ri] and water_id[li] == water_id[ri]:
            uf.union(li, ri)

    # Rule 3 — same name, regardless of carries_type.
    named = valid & pd.notna(pd.array(names, dtype="object"))
    for li, ri in _pairs(g.loc[named, ["geometry"]], name_distance_m):
        if names[li] == names[ri]:
            uf.union(li, ri)

    members: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        members[uf.find(i)].append(i)

    ordered = sorted(
        members.values(), key=lambda idxs: min(str(orig_id[k]) for k in idxs)
    )
    group_id: list[str | None] = [None] * n
    group_size = [0] * n
    for gi, idxs in enumerate(ordered, start=1):
        gid = f"{country}-{gi:06d}"
        for k in idxs:
            group_id[k] = gid
            group_size[k] = len(idxs)

    out["group_id"] = group_id
    out["group_size"] = group_size
    return out


def _assign_water(g: gpd.GeoDataFrame, waterways: gpd.GeoDataFrame, crs: int) -> list:
    """For each feature, the ``water_id`` of the waterway it sits on (within a few metres)."""
    n = len(g)
    if waterways is None or not len(waterways):
        return [None] * n
    wm = waterways.to_crs(crs)[["water_id", "geometry"]]
    nearest = gpd.sjoin_nearest(
        g[["geometry"]], wm, how="left", max_distance=_WATER_SNAP_M, distance_col="_d"
    )
    nearest = nearest[~nearest.index.duplicated(keep="first")]
    return list(nearest["water_id"].reindex(range(n)).to_numpy())
