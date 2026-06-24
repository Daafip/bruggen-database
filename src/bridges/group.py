"""Group OSM features that belong to the same physical bridge.

One real bridge is often mapped as several OSM features: a long viaduct split into
segments, the two carriageways of a divided road, or a ``man_made=bridge`` outline plus the
``bridge=*`` way over it. Left ungrouped, the dataset double-counts and the map shows a
cluster of pins where there is one bridge.

This assigns a shared ``group_id`` to features that are **close together** *and* **carry the
same thing** (``carries_type``), using connected components: two features are linked if they
lie within ``distance_m`` of each other and have an equal ``carries_type``. The
type constraint is what keeps a footbridge from being merged with the car bridge beside it —
``road`` only groups with ``road``, ``foot`` with ``foot``, and so on (a missing
``carries_type``, e.g. a bare structure outline, groups only with other missing-type
features).

``group_id`` is deterministic (groups are numbered by their smallest member OSM id), so a
re-run on the same snapshot is byte-stable.
"""

from __future__ import annotations

from collections import defaultdict

import geopandas as gpd

_NO_TYPE = (
    "__none__"  # sentinel so missing carries_type groups only with itself, not NaN!=NaN
)


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


def assign_groups(
    gdf: gpd.GeoDataFrame,
    distance_m: float = 25.0,
    crs: int = 28992,
    country: str = "NL",
) -> gpd.GeoDataFrame:
    """Return ``gdf`` with ``group_id`` and ``group_size`` columns.

    Features within ``distance_m`` (measured in ``crs``) that share a ``carries_type`` are
    assigned the same ``group_id`` (``"<country>-NNNNNN"``); ``group_size`` is the number of
    features in that group. The input is returned unchanged in order and geometry.
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
    orig_id = out["id"].to_numpy()  # positional, matches g

    uf = _UnionFind(n)
    valid = g.geometry.notna() & ~g.geometry.is_empty
    sub = g.loc[valid, ["geometry"]]
    if len(sub):
        # Self spatial join: every pair of features within distance_m of each other.
        pairs = gpd.sjoin(sub, sub, predicate="dwithin", distance=distance_m)
        for li, ri in zip(pairs.index, pairs["index_right"]):
            if li < ri and ct[li] == ct[ri]:  # same carries_type only
                uf.union(int(li), int(ri))

    members: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        members[uf.find(i)].append(i)

    # Number groups deterministically by their smallest member OSM id.
    ordered = sorted(
        members.values(), key=lambda idxs: min(str(orig_id[k]) for k in idxs)
    )
    group_id = [None] * n
    group_size = [0] * n
    for gi, idxs in enumerate(ordered, start=1):
        gid = f"{country}-{gi:06d}"
        for k in idxs:
            group_id[k] = gid
            group_size[k] = len(idxs)

    out["group_id"] = group_id
    out["group_size"] = group_size
    return out
