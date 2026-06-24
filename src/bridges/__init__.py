"""Bridges of the Netherlands — an OSM-backed bridge database.

A reproducible, free-to-run pipeline that extracts every bridge in a country from
OpenStreetMap, maps its tags to a canonical schema (type, structure, movable mechanism,
what it carries, span length, clearance, load/height limits), and exports GeoJSON / KML /
CSV. Two extract paths — the Overpass API (iterative) and a Geofabrik ``.pbf`` (offline,
scales to a whole country) — feed the same downstream code. Bronze/silver/gold layering
keeps every output traceable to a dated raw snapshot.
"""

__version__ = "0.0.1"
