"""Load per-country bridge configuration from ``config/bridges.yml``.

Keeping every parameter in YAML is what makes "add a country" a config change rather than a
code change.
"""

from __future__ import annotations

import pathlib

import yaml
from pydantic import BaseModel, Field


def project_root() -> pathlib.Path:
    """Repository root (three levels up: src/bridges/config.py -> repo)."""
    return pathlib.Path(__file__).resolve().parents[2]


def default_config_path() -> pathlib.Path:
    return project_root() / "config" / "bridges.yml"


class BridgeConfig(BaseModel):
    """Validated configuration for one country's bridge extraction."""

    iso: str
    osm_area: str
    geofabrik_url: str | None = None
    # Metric CRS (EPSG) for length/width. Default is pan-European LAEA; NL overrides with
    # EPSG:28992 (RD New) for accurate spans.
    proj_crs: int = 3035
    # Optional Overpass area selectors to fetch the country in pieces (one query each,
    # merged into a single snapshot) — for countries too large for a single query.
    regions: list[str] = Field(default_factory=list)


def load_countries(path: str | pathlib.Path | None = None) -> dict[str, BridgeConfig]:
    """Parse the YAML config into validated :class:`BridgeConfig` objects, keyed by code."""
    path = pathlib.Path(path) if path is not None else default_config_path()
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping of country code -> config")
    return {code: BridgeConfig(**block) for code, block in raw.items()}


def get_country(code: str, path: str | pathlib.Path | None = None) -> BridgeConfig:
    """Return the config for one country code (e.g. ``"NL"``), raising if unknown."""
    countries = load_countries(path)
    code = code.upper()
    if code not in countries:
        known = ", ".join(sorted(countries))
        raise KeyError(f"Unknown country {code!r}. Configured: {known}")
    return countries[code]
