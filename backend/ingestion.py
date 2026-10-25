"""
ingestion.py
============
Fetches real data from the Elexon BMRS REST API for:
  - FUELHH  (half-hourly actual fuel-mix generation, filtered to WIND)
  - WINDFOR (hourly wind generation forecasts with publication timestamps)

Strategy
--------
Both /stream endpoints return all records in one JSON array (no pagination
cursor); the only constraint is the date-range window.  The FUELHH endpoint
accepts settlementDateFrom/settlementDateTo; WINDFOR accepts
publishDateTimeFrom/publishDateTimeTo.

For WINDFOR we need ALL forecast vintages published before the day-ahead
cutoff during the study period.  A publication window of
  publishDateTimeFrom = 2025-12-25T00:00:00Z  (covers ≥24-h ahead forecasts)
  publishDateTimeTo   = 2026-01-31T23:59:59Z
retrieves every relevant publication.  The analytics layer then filters by
the configured cutoff.

Caching
-------
Fetched data is written to backend/cache/ as JSON so the full 31-day dataset
is not re-fetched on every API call.  Use force_refresh=True to bypass the
cache.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
CACHE_DIR = Path(__file__).parent / "cache"
TIMEOUT = 60.0  # seconds per request

# Study period (delivery side)
STUDY_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
STUDY_END   = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

# For WINDFOR we fetch publications going back far enough to capture
# ≥24-h lead-time forecasts for Jan 1 delivery.
WINDFOR_PUB_START = "2025-12-25T00:00:00Z"
WINDFOR_PUB_END   = "2026-01-31T23:59:59Z"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def _load_cache(name: str) -> list[dict] | None:
    p = _cache_path(name)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Loaded %d records from cache: %s", len(data), p.name)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache read failed (%s): %s", p.name, exc)
    return None


def _save_cache(name: str, data: list[dict]) -> None:
    _ensure_cache_dir()
    p = _cache_path(name)
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump(data, f)
        logger.info("Saved %d records to cache: %s", len(data), p.name)
    except OSError as exc:
        logger.warning("Cache write failed (%s): %s", p.name, exc)


def _fetch_stream(endpoint: str, params: dict[str, Any]) -> list[dict]:
    """
    Fetch a /stream endpoint from the Elexon BMRS API and return parsed JSON.

    Raises
    ------
    httpx.HTTPStatusError – on 4xx / 5xx responses
    httpx.RequestError    – on network failures
    ValueError            – if the response is not a JSON list
    """
    url = f"{BASE_URL}/{endpoint}/stream"
    logger.info("GET %s  params=%s", url, params)
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(
            f"Expected JSON list from {url}, got {type(data).__name__}"
        )
    logger.info("Received %d records from %s", len(data), endpoint)
    return data


# ---------------------------------------------------------------------------
# FUELHH – actual wind generation
# ---------------------------------------------------------------------------

def _fetch_fuelhh_chunk(date_from: str, date_to: str) -> list[dict]:
    """Fetch FUELHH for a date range, filtered to WIND."""
    return _fetch_stream(
        "FUELHH",
        {
            "settlementDateFrom": date_from,
            "settlementDateTo":   date_to,
            "fuelType":           "WIND",
        },
    )


def fetch_actuals(force_refresh: bool = False) -> list[dict]:
    """
    Return all WIND actual-generation records for January 2026.

    Each record contains:
      - startTime    (UTC ISO-8601 string)
      - generation   (MW, integer)
      - fuelType     ("WIND")
      - settlementDate / settlementPeriod

    The FUELHH /stream endpoint can return up to 31 days in one call,
    so we fetch the month in a single request.

    Timestamps are all UTC (the API returns 'Z' suffix).
    """
    cache_name = "fuelhh_jan2026_wind"
    if not force_refresh:
        cached = _load_cache(cache_name)
        if cached is not None:
            return cached

    records = _fetch_fuelhh_chunk("2026-01-01", "2026-01-31")

    # Defensive validation
    validated: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            logger.warning("Skipping non-dict FUELHH record: %r", r)
            continue
        if r.get("fuelType") != "WIND":
            continue  # belt-and-braces: API param may not filter
        if r.get("generation") is None or r["generation"] < 0:
            logger.warning("Skipping record with invalid generation: %r", r)
            continue
        if not r.get("startTime"):
            continue
        validated.append(r)

    # Deduplicate by startTime (keep the record if there are dupes)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in validated:
        key = r["startTime"]
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    logger.info(
        "FUELHH validated: %d records (%d dupes removed)",
        len(deduped), len(validated) - len(deduped),
    )

    _save_cache(cache_name, deduped)
    return deduped


# ---------------------------------------------------------------------------
# WINDFOR – forecast wind generation
# ---------------------------------------------------------------------------

def fetch_forecasts(force_refresh: bool = False) -> list[dict]:
    """
    Return all WINDFOR forecast records whose publishTime falls in
    [2025-12-25, 2026-01-31].

    Each record contains:
      - startTime   (delivery hour, UTC ISO-8601 string)
      - publishTime (forecast publication timestamp, UTC ISO-8601 string)
      - generation  (MW, integer)

    The WINDFOR stream endpoint is queried by publishDateTimeFrom/To.
    Multiple publications exist per delivery interval; the analytics layer
    selects the appropriate one via the day-ahead cutoff.

    Note on granularity: WINDFOR is hourly; FUELHH is half-hourly.
    The matching logic in analytics.py handles this by aligning FUELHH
    pairs of consecutive 30-min periods to the matching WINDFOR hour.
    """
    cache_name = "windfor_jan2026"
    if not force_refresh:
        cached = _load_cache(cache_name)
        if cached is not None:
            return cached

    records = _fetch_stream(
        "WINDFOR",
        {
            "publishDateTimeFrom": WINDFOR_PUB_START,
            "publishDateTimeTo":   WINDFOR_PUB_END,
        },
    )

    validated: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("generation") is None or r["generation"] < 0:
            logger.warning("Skipping WINDFOR record with invalid generation: %r", r)
            continue
        if not r.get("startTime") or not r.get("publishTime"):
            continue
        validated.append(r)

    # Deduplicate by (startTime, publishTime)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in validated:
        key = (r["startTime"], r["publishTime"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    logger.info(
        "WINDFOR validated: %d records (%d dupes removed)",
        len(deduped), len(validated) - len(deduped),
    )

    _save_cache(cache_name, deduped)
    return deduped
