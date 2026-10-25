"""
analytics.py
============
Core analytics engine for WindSight UK.

Design decisions (documented for the assignment)
-------------------------------------------------
1. Granularity alignment
   FUELHH delivers 30-min half-hourly actuals; WINDFOR delivers hourly
   forecasts.  We aggregate each pair of consecutive FUELHH half-hours
   into an hourly total so they can be compared with WINDFOR on the same
   time axis.  The WINDFOR startTime marks the *start* of the delivery
   hour (e.g. 00:00 → 01:00 UTC).

2. Day-ahead cutoff
   The application models a decision cutoff of 11:00 UTC on the calendar
   day *before* delivery. This is an assignment assumption, not a verified
   rule for a specific buyer or procurement contract.
   For delivery on 2026-01-02 00:00 UTC, the cutoff is 2026-01-01 11:00 UTC.
   This is configurable via CUTOFF_HOUR_UTC.

3. Forecast selection per interval
   For each delivery hour we collect all forecasts whose publishTime is
   ≤ cutoff.  We select the LATEST such publication (most up-to-date
   information available before the decision).  This is the "purchased
   forecast" – what a buyer would have used.

4. Lead-time
   lead_time_hours = (delivery startTime − publishTime) / 3600
    Two available bands: ≥20 h and 10–20 h. With a previous-day 11:00 UTC
    cutoff, the selected forecast cannot have a lead time below 10 hours.

5. Error convention
   error_mw = forecast_mw − actual_mw
   Positive → overforecast; negative → underforecast.

6. MAPE
   MAPE is undefined when actual = 0.  We skip those intervals from MAPE
   calculation and report coverage separately.

7. Missing data
   Intervals present in actuals but not in (qualifying) forecasts, and
   vice versa, are reported as missing and excluded from metric calculations.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Hour (UTC) of the day-ahead purchasing cutoff on the day *before* delivery.
# Assignment modeling assumption: prior-day cutoff at 11:00 UTC.
CUTOFF_HOUR_UTC: int = 11

# Lead-time bands. The cutoff means selected forecasts cannot enter a <10h band.
LEAD_TIME_BANDS = {
    "~24h (≥20h)":   (20.0, float("inf")),
    "~12h (10–20h)": (10.0, 20.0),
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp string to an aware datetime."""
    ts = ts.rstrip("Z")
    # Handle both 'YYYY-MM-DDTHH:MM:SS' and 'YYYY-MM-DDTHH:MM:SS.ffffff'
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        # Fallback for non-standard variants
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Step 1 – Aggregate FUELHH half-hours → hourly actuals (MW)
# ---------------------------------------------------------------------------

def build_hourly_actuals(fuelhh_records: list[dict]) -> dict[datetime, float]:
    """
    Aggregate FUELHH 30-min records into hourly MW totals.

    WINDFOR is hourly.  Each WINDFOR startTime represents one delivery hour
    (e.g. 2026-01-01T00:00:00Z covers 00:00–01:00).  We sum both FUELHH
    half-hours that fall within that hour and average them to get an
    equivalent hourly MW figure (arithmetic mean of the two 30-min readings,
    since generation is already in MW not MWh).

    Returns
    -------
    dict mapping delivery_hour_utc -> mean_mw
    """
    # Only form hours from both distinct expected half-hour readings.
    hourly_values: dict[datetime, dict[int, float]] = {}
    for r in fuelhh_records:
        try:
            st = _parse_utc(r["startTime"])
        except (KeyError, ValueError) as exc:
            logger.debug("Skipping badly-formed FUELHH record: %s", exc)
            continue
        if st.minute not in (0, 30) or st.second or st.microsecond:
            logger.warning("Skipping FUELHH record off a half-hour boundary: %s", r.get("startTime"))
            continue
        hour_key = st.replace(minute=0, second=0, microsecond=0)
        hourly_values.setdefault(hour_key, {})[st.minute] = float(r["generation"])

    # Incomplete hours remain missing instead of being treated as complete.
    result: dict[datetime, float] = {}
    for hour, values in hourly_values.items():
        if 0 in values and 30 in values:
            result[hour] = (values[0] + values[30]) / 2
        else:
            logger.warning("Excluding incomplete FUELHH hour %s", hour.isoformat())
    return result


# ---------------------------------------------------------------------------
# Step 2 – Build cutoff for a delivery datetime
# ---------------------------------------------------------------------------

def cutoff_for_delivery(delivery_dt: datetime) -> datetime:
    """
    Return the day-ahead decision cutoff for a given delivery datetime.

    The cutoff is CUTOFF_HOUR_UTC on the calendar day preceding the delivery
    date.  Any forecast published after this cutoff would not have been
    available to the buyer.

    Example: delivery at 2026-01-15 14:00 UTC → cutoff 2026-01-14 11:00 UTC
    """
    delivery_date = delivery_dt.date()
    prev_day = delivery_date - timedelta(days=1)
    return datetime(
        prev_day.year, prev_day.month, prev_day.day,
        CUTOFF_HOUR_UTC, 0, 0,
        tzinfo=timezone.utc,
    )


# ---------------------------------------------------------------------------
# Step 3 – Select the best qualifying forecast per delivery interval
# ---------------------------------------------------------------------------

def select_forecasts(
    windfor_records: list[dict],
    delivery_hours: set[datetime],
) -> dict[datetime, dict]:
    """
    For each delivery hour, select the latest forecast published at or before
    the day-ahead cutoff.

    Parameters
    ----------
    windfor_records  : all WINDFOR records (arbitrary order)
    delivery_hours   : delivery hours we need forecasts for

    Returns
    -------
    dict mapping delivery_hour_utc -> {
        "forecast_mw": float,
        "publish_time": datetime,
        "lead_time_h":  float,
        "cutoff":       datetime,
    }
    """
    # Index all forecasts by delivery hour
    by_delivery: dict[datetime, list[dict]] = {}
    for r in windfor_records:
        try:
            st = _parse_utc(r["startTime"])
            pt = _parse_utc(r["publishTime"])
        except (KeyError, ValueError) as exc:
            logger.debug("Skipping badly-formed WINDFOR record: %s", exc)
            continue
        # Normalise to top-of-hour (WINDFOR is already hourly but be safe)
        st = st.replace(minute=0, second=0, microsecond=0)
        if st in delivery_hours:
            by_delivery.setdefault(st, []).append(
                {"forecast_mw": float(r["generation"]), "publish_time": pt, "raw_st": st}
            )

    selected: dict[datetime, dict] = {}
    for delivery_dt in delivery_hours:
        cutoff = cutoff_for_delivery(delivery_dt)
        candidates = [
            f for f in by_delivery.get(delivery_dt, [])
            if f["publish_time"] <= cutoff
        ]
        if not candidates:
            continue  # no qualifying forecast
        # Pick the latest publication (most informative before cutoff)
        best = max(candidates, key=lambda f: f["publish_time"])
        lead = (delivery_dt - best["publish_time"]).total_seconds() / 3600.0
        selected[delivery_dt] = {
            "forecast_mw":  best["forecast_mw"],
            "publish_time": best["publish_time"],
            "lead_time_h":  lead,
            "cutoff":       cutoff,
        }
    return selected


# ---------------------------------------------------------------------------
# Step 4 – Match actuals with selected forecasts
# ---------------------------------------------------------------------------

def match_records(
    hourly_actuals: dict[datetime, float],
    selected_forecasts: dict[datetime, dict],
    study_start: datetime,
    study_end: datetime,
) -> tuple[list[dict], dict]:
    """
    Produce a list of matched observation records and a coverage summary.

    Returns
    -------
    matched     : list of dicts with delivery_time, actual_mw, forecast_mw,
                  error_mw, publish_time, lead_time_h, cutoff
    coverage    : dict with counts and lists of missing intervals
    """
    first_hour = study_start.replace(minute=0, second=0, microsecond=0)
    last_hour = study_end.replace(minute=0, second=0, microsecond=0)
    study_hours: set[datetime] = set()
    cursor = first_hour
    while cursor <= last_hour:
        study_hours.add(cursor)
        cursor += timedelta(hours=1)

    matched: list[dict] = []
    missing_forecast: list[str] = []
    missing_actual: list[str] = []

    for delivery_dt in sorted(study_hours):
        has_actual = delivery_dt in hourly_actuals
        has_forecast = delivery_dt in selected_forecasts
        if has_actual and has_forecast:
            actual_mw = hourly_actuals[delivery_dt]
            fc = selected_forecasts[delivery_dt]
            error_mw = fc["forecast_mw"] - actual_mw
            matched.append({
                "delivery_time":  delivery_dt.isoformat(),
                "actual_mw":      round(actual_mw, 2),
                "forecast_mw":    round(fc["forecast_mw"], 2),
                "error_mw":       round(error_mw, 2),
                "publish_time":   fc["publish_time"].isoformat(),
                "lead_time_h":    round(fc["lead_time_h"], 2),
                "cutoff":         fc["cutoff"].isoformat(),
            })
        elif has_actual:
            missing_forecast.append(delivery_dt.isoformat())
        if not has_actual:
            missing_actual.append(delivery_dt.isoformat())

    coverage = {
        "matched_count":          len(matched),
        "total_actual_hours":     sum(1 for dt in hourly_actuals if dt in study_hours),
        "total_expected_hours":   len(study_hours),
        "missing_forecast_count": len(missing_forecast),
        "missing_actual_count":   len(missing_actual),
        "missing_forecast_hours": missing_forecast,
        "missing_actual_hours":   missing_actual,
        "coverage_pct":           (
            round(len(matched) / len(study_hours) * 100, 2)
            if study_hours else 0.0
        ),
    }
    return matched, coverage


# ---------------------------------------------------------------------------
# Step 5 – Accuracy metrics
# ---------------------------------------------------------------------------

def compute_metrics(matched: list[dict]) -> dict:
    """
    Compute MAE, RMSE, Bias, MAPE from matched records.

    error_mw = forecast_mw − actual_mw  (positive = overforecast)

    MAPE is computed only for records where actual_mw > 0.
    """
    if not matched:
        return {
            "mae_mw":    None,
            "rmse_mw":   None,
            "bias_mw":   None,
            "mape_pct":  None,
            "n":         0,
            "n_mape":    0,
        }

    errors = [r["error_mw"] for r in matched]
    actuals = [r["actual_mw"] for r in matched]

    n = len(errors)
    mae  = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
    bias = sum(errors) / n

    # MAPE – exclude zero actuals
    mape_terms = [
        abs(e / a) * 100.0
        for e, a in zip(errors, actuals)
        if a > 0
    ]
    mape = sum(mape_terms) / len(mape_terms) if mape_terms else None

    return {
        "mae_mw":   round(mae, 2),
        "rmse_mw":  round(rmse, 2),
        "bias_mw":  round(bias, 2),
        "mape_pct": round(mape, 2) if mape is not None else None,
        "n":        n,
        "n_mape":   len(mape_terms),
    }


# ---------------------------------------------------------------------------
# Step 6 – Lead-time analysis
# ---------------------------------------------------------------------------

def compute_lead_time_metrics(matched: list[dict]) -> list[dict]:
    """
    Split matched records into lead-time bands and compute metrics per band.

    Lead time = delivery_time − publish_time (hours).
    Bands are defined in LEAD_TIME_BANDS.
    """
    bands: dict[str, list[dict]] = {band: [] for band in LEAD_TIME_BANDS}
    for r in matched:
        lt = r["lead_time_h"]
        for band, (lo, hi) in LEAD_TIME_BANDS.items():
            if lo <= lt < hi:
                bands[band].append(r)
                break

    results = []
    for band_name, records in bands.items():
        metrics = compute_metrics(records)
        lo, hi = LEAD_TIME_BANDS[band_name]
        results.append({
            "band":     band_name,
            "min_lead": lo,
            "max_lead": hi if hi != float("inf") else None,
            "count":    len(records),
            **metrics,
        })
    return results


# ---------------------------------------------------------------------------
# High-level pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    fuelhh_records: list[dict],
    windfor_records: list[dict],
    study_start: datetime | None = None,
    study_end:   datetime | None = None,
) -> dict[str, Any]:
    """
    Run the full WindSight UK analytics pipeline.

    Returns a dict with:
      matched          – per-interval detail records
      coverage         – data coverage statistics
      summary_metrics  – MAE, RMSE, Bias, MAPE for whole period
      lead_time_metrics – per-band accuracy breakdown
      cutoff_hour_utc  – configured cutoff hour for transparency
    """
    from ingestion import STUDY_START, STUDY_END  # local import to avoid circular

    if study_start is None:
        study_start = STUDY_START
    if study_end is None:
        study_end = STUDY_END

    logger.info(
        "Running pipeline: %s → %s",
        study_start.date(), study_end.date(),
    )

    hourly_actuals = build_hourly_actuals(fuelhh_records)
    first_hour = study_start.replace(minute=0, second=0, microsecond=0)
    last_hour = study_end.replace(minute=0, second=0, microsecond=0)
    delivery_hours: set[datetime] = set()
    cursor = first_hour
    while cursor <= last_hour:
        delivery_hours.add(cursor)
        cursor += timedelta(hours=1)
    selected = select_forecasts(windfor_records, delivery_hours)
    matched, coverage = match_records(
        hourly_actuals, selected, study_start, study_end
    )
    metrics = compute_metrics(matched)
    lt_metrics = compute_lead_time_metrics(matched)

    return {
        "matched":           matched,
        "coverage":          coverage,
        "summary_metrics":   metrics,
        "lead_time_metrics": lt_metrics,
        "cutoff_hour_utc":   CUTOFF_HOUR_UTC,
        "study_period": {
            "from": study_start.isoformat(),
            "to":   study_end.isoformat(),
        },
    }
