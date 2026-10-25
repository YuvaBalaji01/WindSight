"""
routes.py
=========
WindSight UK – API route definitions.

All routes are collected into an APIRouter and registered in main.py.
"""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
import httpx

from analytics import run_pipeline
from ingestion import STUDY_END, STUDY_START, fetch_actuals, fetch_forecasts

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# In-process result cache (prevents full re-computation on every request)
# ---------------------------------------------------------------------------

_PIPELINE_CACHE: dict[str, Any] = {}


def _get_pipeline_result(force_refresh: bool = False) -> dict[str, Any]:
    """
    Run (or return cached) the full January 2026 pipeline result.
    The result is cached in memory for the lifetime of the process.
    """
    global _PIPELINE_CACHE
    if _PIPELINE_CACHE and not force_refresh:
        return _PIPELINE_CACHE

    logger.info("Running pipeline (force_refresh=%s)…", force_refresh)
    try:
        fuelhh   = fetch_actuals(force_refresh=force_refresh)
        windfor  = fetch_forecasts(force_refresh=force_refresh)
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Elexon data retrieval failed")
        raise HTTPException(status_code=503, detail="Elexon data is temporarily unavailable; retry later.") from exc
    _PIPELINE_CACHE = run_pipeline(fuelhh, windfor)
    return _PIPELINE_CACHE


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/forecast-accuracy/summary")
def forecast_accuracy_summary(
    from_date: str = Query(
        default="2026-01-01",
        alias="from",
        description="Start date (YYYY-MM-DD), inclusive",
    ),
    to_date: str = Query(
        default="2026-01-31",
        alias="to",
        description="End date (YYYY-MM-DD), inclusive",
    ),
    refresh: bool = Query(default=False, description="Force refresh from Elexon API"),
) -> dict:
    """
    Return overall accuracy metrics and data coverage for a date range.
    """
    try:
        dt_from = datetime.combine(date_type.fromisoformat(from_date), datetime.min.time(), tzinfo=timezone.utc)
        dt_to   = datetime.combine(date_type.fromisoformat(to_date), datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}") from exc

    _validate_date_range(dt_from, dt_to)

    result = _get_pipeline_result(force_refresh=refresh)
    # Filter matched records to requested range
    matched = _filter_matched(result["matched"], dt_from, dt_to)

    from analytics import compute_metrics
    metrics = compute_metrics(matched)

    return {
        "from":             from_date,
        "to":               to_date,
        "cutoff_hour_utc":  result["cutoff_hour_utc"],
        "summary_metrics":  metrics,
        "coverage":         _coverage_for_range(result["matched"], dt_from, dt_to, result["coverage"]),
    }


@router.get("/api/forecast-accuracy")
def forecast_accuracy_day(
    date: str = Query(description="Delivery date (YYYY-MM-DD)"),
    refresh: bool = Query(default=False),
) -> dict:
    """
    Return per-interval detail for a single delivery date.
    """
    try:
        parsed_date = date_type.fromisoformat(date)
        dt_from = datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
        dt_to   = datetime.combine(parsed_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}") from exc

    _validate_date_range(dt_from, dt_to)

    result = _get_pipeline_result(force_refresh=refresh)
    matched = _filter_matched(result["matched"], dt_from, dt_to)

    from analytics import compute_metrics
    metrics = compute_metrics(matched)

    return {
        "date":             date,
        "cutoff_hour_utc":  result["cutoff_hour_utc"],
        "intervals":        matched,
        "metrics":          metrics,
        "count":            len(matched),
        "coverage":         _coverage_for_range(result["matched"], dt_from, dt_to, result["coverage"]),
    }


@router.get("/api/forecast-accuracy/lead-times")
def forecast_lead_times(
    from_date: str = Query(default="2026-01-01", alias="from"),
    to_date:   str = Query(default="2026-01-31", alias="to"),
    refresh:   bool = Query(default=False),
) -> dict:
    """
    Return accuracy metrics broken down by forecast lead-time band.
    """
    try:
        dt_from = datetime.combine(date_type.fromisoformat(from_date), datetime.min.time(), tzinfo=timezone.utc)
        dt_to   = datetime.combine(date_type.fromisoformat(to_date), datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}") from exc

    _validate_date_range(dt_from, dt_to)

    result  = _get_pipeline_result(force_refresh=refresh)
    matched = _filter_matched(result["matched"], dt_from, dt_to)

    from analytics import compute_lead_time_metrics
    lt_metrics = compute_lead_time_metrics(matched)

    return {
        "from":             from_date,
        "to":               to_date,
        "cutoff_hour_utc":  result["cutoff_hour_utc"],
        "lead_time_bands":  lt_metrics,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_date_range(dt_from: datetime, dt_to: datetime) -> None:
    if dt_from > dt_to:
        raise HTTPException(status_code=422, detail="'from' must not exceed 'to'")
    if dt_from < STUDY_START or dt_to > STUDY_END:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Date range must be within the study period "
                f"{STUDY_START.date()} – {STUDY_END.date()}"
            ),
        )


def _filter_matched(
    matched: list[dict], dt_from: datetime, dt_to: datetime
) -> list[dict]:
    """Return matched records whose delivery_time falls in [dt_from, dt_to]."""
    result = []
    for r in matched:
        dt = datetime.fromisoformat(r["delivery_time"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt_from <= dt <= dt_to:
            result.append(r)
    return result


def _coverage_for_range(
    matched: list[dict],
    dt_from: datetime,
    dt_to:   datetime,
    full_coverage: dict,
) -> dict:
    """Build a coverage summary restricted to the requested date range."""
    filtered = _filter_matched(matched, dt_from, dt_to)
    n_matched = len(filtered)
    # Estimate total expected hours in range
    delta_h = int((dt_to - dt_from).total_seconds() / 3600) + 1
    return {
        "matched_count":    n_matched,
        "expected_hours":   delta_h,
        "missing_actual_count": sum(1 for x in full_coverage.get("missing_actual_hours", []) if dt_from <= datetime.fromisoformat(x) <= dt_to),
        "missing_forecast_count": sum(1 for x in full_coverage.get("missing_forecast_hours", []) if dt_from <= datetime.fromisoformat(x) <= dt_to),
        "coverage_pct":     round(n_matched / delta_h * 100, 2) if delta_h else 0.0,
    }
