"""Lightweight self-contained HTML map of the bridge dataset (Leaflet via folium).

The full GeoJSON is too large for Google's preview, so this renders the points into a
single HTML file with the data embedded. Features are first **collapsed by ``group_id``**
(see :mod:`bridges.group`) so one physical bridge is one marker, not the cluster of segments
OSM splits it into:

* **All bridges** — a client-side cluster (``FastMarkerCluster``) of one point per group;
  each is clickable for a popup with name, type, what it carries, and length / width.
* **Movable bridges** — the navigation-relevant subset (a group is movable if any of its
  features is), as colour-coded markers with richer popups (name, type, mechanism, what it
  carries, length / width, segment count, OSM link).

The HTML is one file with the data inlined; Leaflet itself and the map tiles load from
their usual CDN / tile servers, so an internet connection is needed to *render* it (true of
any web map), but no separate data file is required.
"""

from __future__ import annotations

import html
import pathlib

import pandas as pd

# Colour per movable mechanism (the high-value navigation attribute).
MOVABLE_COLOURS = {
    "bascule": "red",
    "swing": "blue",
    "lift": "green",
    "drawbridge": "purple",
    "retractable": "orange",
    "tilt": "darkred",
    "transporter": "cadetblue",
}
DEFAULT_MOVABLE_COLOUR = "gray"

NL_CENTER = [52.15, 5.3]


def _clean(value):
    return value if isinstance(value, str) and value.strip() else None


def _is_true(series: pd.Series) -> pd.Series:
    """Robust boolean mask, whether the column round-tripped as bool or as ``"True"`` text."""
    return series.map(lambda v: str(v).strip().lower() == "true")


def _first(series: pd.Series):
    """First non-blank value in a group, else None."""
    for v in series:
        if isinstance(v, str) and v.strip():
            return v
    return None


def _fmt(value, decimals: int = 0) -> str:
    """Format a numeric stat for display, or '' when missing."""
    try:
        return "" if pd.isna(value) else f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return ""


def _collapse_to_groups(df: pd.DataFrame) -> pd.DataFrame:
    """One row per physical bridge: collapse features sharing a ``group_id``.

    The representative point is the group's stored ``group_lat``/``group_lon`` (mean of its
    members), a group counts as movable if any of its features is, ``length_m`` is the summed
    member length and ``width_m`` the max. Returns ``df`` unchanged without a ``group_id``.
    """
    if "group_id" not in df.columns or df["group_id"].isna().all():
        return df
    grp = df.groupby("group_id", sort=False)
    if "group_lat" in df.columns and df["group_lat"].notna().any():
        lat, lon = grp["group_lat"].first(), grp["group_lon"].first()
    else:
        lat, lon = grp["lat"].mean(), grp["lon"].mean()
    agg = {
        "lat": lat,
        "lon": lon,
        "name": grp["name"].apply(_first),
        "bridge_type": grp["bridge_type"].apply(_first),
        "carries": grp["carries"].apply(_first),
        "movable": grp["movable"].apply(_first),
        "osm_url": grp["osm_url"].apply(_first),
        "is_movable": grp["is_movable"].apply(lambda s: bool(_is_true(s).any())),
        "n_features": grp.size(),
    }
    # Total length across the group's segments; widest member. (min_count=1 keeps NaN when
    # nothing is tagged rather than collapsing to 0.)
    if "length_m" in df.columns:
        agg["length_m"] = grp["length_m"].sum(min_count=1)
    if "width_m" in df.columns:
        agg["width_m"] = grp["width_m"].max()
    return pd.DataFrame(agg).reset_index()


def build_viewer(
    csv_path: str | pathlib.Path,
    out_html: str | pathlib.Path,
    country: str = "NL",
    center: list[float] | None = None,
    zoom: int = 8,
) -> pathlib.Path:
    """Build the HTML viewer from a canonical ``bridges_<C>.csv`` and return its path."""
    import folium
    from folium.plugins import FastMarkerCluster

    csv_path = pathlib.Path(csv_path)
    out_html = pathlib.Path(out_html)
    df = pd.read_csv(csv_path, low_memory=False)
    df = df.dropna(subset=["lat", "lon"])
    # Collapse the OSM features of each physical bridge to a single representative point.
    df = _collapse_to_groups(df)

    m = folium.Map(location=center or NL_CENTER, zoom_start=zoom, tiles="OpenStreetMap")
    e = html.escape

    # Layer 1 — every bridge, clustered. A callback builds a marker + popup per point from
    # compact data rows (name, type, carries, length, width), so all bridges are clickable
    # without one heavy Python marker object each.
    rows = [
        [
            float(r.lat),
            float(r.lon),
            e(_clean(r.name) or ""),
            e(_clean(r.bridge_type) or ""),
            e(_clean(r.carries) or ""),
            _fmt(getattr(r, "length_m", None), 0),
            _fmt(getattr(r, "width_m", None), 1),
        ]
        for r in df.itertuples(index=False)
    ]
    callback = """
        function (row) {
            var html = '<b>' + (row[2] || 'Bridge') + '</b>';
            if (row[3]) { html += '<br>type: ' + row[3]; }
            if (row[4]) { html += '<br>carries: ' + row[4]; }
            if (row[5]) { html += '<br>length: ' + row[5] + ' m'; }
            if (row[6]) { html += '<br>width: ' + row[6] + ' m'; }
            return L.circleMarker(new L.LatLng(row[0], row[1]),
                {radius: 3, color: '#2b6cb0', weight: 1, fillOpacity: 0.6}).bindPopup(html);
        }
    """
    fg_all = folium.FeatureGroup(name=f"All bridges ({len(df):,})", show=True)
    FastMarkerCluster(data=rows, callback=callback).add_to(fg_all)
    fg_all.add_to(m)

    # Layer 2 — movable bridges, colour-coded with popups.
    movable = df[_is_true(df["is_movable"])]
    fg_mov = folium.FeatureGroup(name=f"Movable bridges ({len(movable):,})", show=True)
    for _, r in movable.iterrows():
        mech = _clean(r.get("movable")) or "movable"
        colour = MOVABLE_COLOURS.get(mech, DEFAULT_MOVABLE_COLOUR)
        name = _clean(r.get("name")) or "(unnamed)"
        carries = _clean(r.get("carries")) or "?"
        btype = _clean(r.get("bridge_type")) or "?"
        url = _clean(r.get("osm_url"))
        n_feat = int(r.get("n_features", 1) or 1)
        seg = f"segments: {n_feat}<br>" if n_feat > 1 else ""
        length = _fmt(r.get("length_m"), 0)
        width = _fmt(r.get("width_m"), 1)
        stats = (f"length: {length} m<br>" if length else "") + (
            f"width: {width} m<br>" if width else ""
        )
        # Escape free-text OSM values (names can contain &, <, quotes) before HTML interpolation.
        popup = folium.Popup(
            f"<b>{e(name)}</b><br>"
            f"type: {e(btype)}<br>"
            f"mechanism: {e(mech)}<br>"
            f"carries: {e(carries)}<br>"
            f"{stats}"
            f"{seg}"
            + (
                f'<a href="{e(url, quote=True)}" target="_blank">OSM</a>' if url else ""
            ),
            max_width=260,
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=4,
            color=colour,
            fill=True,
            fill_opacity=0.8,
            popup=popup,
            tooltip=e(name) if name != "(unnamed)" else e(mech),
        ).add_to(fg_mov)
    fg_mov.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    _add_legend(m, country, len(df), len(movable))

    out_html.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_html))
    return out_html


def _add_legend(m, country: str, n_total: int, n_movable: int) -> None:
    """Add a small fixed-position legend/title box to the map."""
    import folium

    swatches = "".join(
        f'<span style="display:inline-block;width:10px;height:10px;'
        f'background:{c};border-radius:50%;margin-right:4px"></span>{k}<br>'
        for k, c in list(MOVABLE_COLOURS.items())
    )
    legend_html = (
        '<div style="position:fixed;bottom:20px;left:20px;z-index:9999;'
        "background:white;padding:10px 12px;border:1px solid #999;border-radius:6px;"
        'font:12px/1.4 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)">'
        f"<b>Bridges of {country}</b><br>"
        f"{n_total:,} bridges · {n_movable:,} movable<br>"
        '<hr style="margin:6px 0">'
        "<b>movable mechanism</b><br>"
        f"{swatches}"
        f'<span style="display:inline-block;width:10px;height:10px;'
        f'background:{DEFAULT_MOVABLE_COLOUR};border-radius:50%;margin-right:4px"></span>other'
        "</div>"
    )
    m.get_root().html.add_child(folium.Element(legend_html))
