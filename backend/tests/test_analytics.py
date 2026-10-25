"""
test_analytics.py
=================
Automated unit tests for the WindSight UK analytics engine.

All fixtures are SYNTHETIC TEST DATA and are clearly labelled as such.
They are used only for unit testing and never displayed as real observations.

Run with:
  cd backend
  pip install -r requirements-dev.txt
  pytest tests/ -v
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

# Import the functions under test
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analytics import (
    CUTOFF_HOUR_UTC,
    LEAD_TIME_BANDS,
    build_hourly_actuals,
    compute_lead_time_metrics,
    compute_metrics,
    cutoff_for_delivery,
    match_records,
    select_forecasts,
)


# ---------------------------------------------------------------------------
# Helpers (synthetic data factories – clearly labelled as TEST DATA)
# ---------------------------------------------------------------------------

def _utc(year, month, day, hour=0, minute=0, second=0):
    """Helper: create a UTC datetime (TEST DATA helper)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _fuelhh(start_iso: str, generation: float) -> dict:
    """Synthetic FUELHH record (TEST DATA)."""
    return {
        "dataset":       "FUELHH",
        "startTime":     start_iso,
        "generation":    generation,
        "fuelType":      "WIND",
        "settlementDate": start_iso[:10],
    }


def _windfor(start_iso: str, publish_iso: str, generation: float) -> dict:
    """Synthetic WINDFOR record (TEST DATA)."""
    return {
        "dataset":     "WINDFOR",
        "startTime":   start_iso,
        "publishTime": publish_iso,
        "generation":  generation,
    }


# ---------------------------------------------------------------------------
# Tests: build_hourly_actuals
# ---------------------------------------------------------------------------

class TestBuildHourlyActuals:
    """SYNTHETIC TEST DATA – not real Elexon observations."""

    def test_two_half_hours_averaged(self):
        records = [
            _fuelhh("2026-01-15T12:00:00Z", 10000),
            _fuelhh("2026-01-15T12:30:00Z", 12000),
        ]
        result = build_hourly_actuals(records)
        key = _utc(2026, 1, 15, 12)
        assert key in result
        assert result[key] == pytest.approx(11000.0)

    def test_single_half_hour_is_excluded_as_incomplete(self):
        records = [_fuelhh("2026-01-15T06:00:00Z", 8000)]
        result = build_hourly_actuals(records)
        key = _utc(2026, 1, 15, 6)
        assert key not in result

    def test_duplicate_half_hour_does_not_hide_missing_period(self):
        records = [
            _fuelhh("2026-01-15T06:00:00Z", 8000),
            _fuelhh("2026-01-15T06:00:00Z", 9000),
        ]
        assert _utc(2026, 1, 15, 6) not in build_hourly_actuals(records)

    def test_empty_input(self):
        assert build_hourly_actuals([]) == {}

    def test_skips_malformed_record(self):
        records = [
            {"bad": "record"},
            _fuelhh("2026-01-01T00:00:00Z", 5000),
            _fuelhh("2026-01-01T00:30:00Z", 7000),
        ]
        result = build_hourly_actuals(records)
        assert len(result) == 1
        assert result[_utc(2026, 1, 1, 0)] == pytest.approx(6000.0)

    def test_multiple_hours(self):
        records = [
            _fuelhh("2026-01-01T00:00:00Z", 4000),
            _fuelhh("2026-01-01T00:30:00Z", 6000),
            _fuelhh("2026-01-01T01:00:00Z", 8000),
            _fuelhh("2026-01-01T01:30:00Z", 10000),
        ]
        result = build_hourly_actuals(records)
        assert result[_utc(2026, 1, 1, 0)] == pytest.approx(5000.0)
        assert result[_utc(2026, 1, 1, 1)] == pytest.approx(9000.0)


# ---------------------------------------------------------------------------
# Tests: cutoff_for_delivery
# ---------------------------------------------------------------------------

class TestCutoffForDelivery:
    """Tests for day-ahead cutoff logic."""

    def test_standard_day(self):
        # Delivery 2026-01-15 14:00 → cutoff 2026-01-14 11:00 UTC
        delivery = _utc(2026, 1, 15, 14)
        expected = _utc(2026, 1, 14, CUTOFF_HOUR_UTC)
        assert cutoff_for_delivery(delivery) == expected

    def test_midnight_delivery(self):
        # Delivery at 00:00 on the 2nd → cutoff on the 1st
        delivery = _utc(2026, 1, 2, 0)
        expected = _utc(2026, 1, 1, CUTOFF_HOUR_UTC)
        assert cutoff_for_delivery(delivery) == expected

    def test_month_boundary(self):
        delivery = _utc(2026, 1, 1, 6)
        expected = _utc(2025, 12, 31, CUTOFF_HOUR_UTC)
        assert cutoff_for_delivery(delivery) == expected


# ---------------------------------------------------------------------------
# Tests: select_forecasts
# ---------------------------------------------------------------------------

class TestSelectForecasts:
    """SYNTHETIC TEST DATA – not real Elexon observations."""

    BASE_DELIVERY = _utc(2026, 1, 15, 12)
    CUTOFF = _utc(2026, 1, 14, CUTOFF_HOUR_UTC)  # day before at 11:00 UTC

    def test_selects_latest_before_cutoff(self):
        # Two forecasts both before cutoff; should pick the later one.
        early_pub  = _utc(2026, 1, 14, 8)   # 08:00 → before cutoff
        latest_pub = _utc(2026, 1, 14, 10)  # 10:00 → before cutoff (latest valid)
        after_pub  = _utc(2026, 1, 14, 13)  # 13:00 → AFTER cutoff, must be excluded

        records = [
            _windfor("2026-01-15T12:00:00Z", early_pub.isoformat() + "Z",  9000),
            _windfor("2026-01-15T12:00:00Z", latest_pub.isoformat() + "Z", 9200),
            _windfor("2026-01-15T12:00:00Z", after_pub.isoformat() + "Z",  9500),
        ]
        result = select_forecasts(records, {self.BASE_DELIVERY})
        assert self.BASE_DELIVERY in result
        # 9500 is after cutoff, 9200 is the latest valid
        assert result[self.BASE_DELIVERY]["forecast_mw"] == pytest.approx(9200.0)

    def test_excludes_post_cutoff_forecasts(self):
        # All forecasts are after the cutoff → no result
        after_pub = _utc(2026, 1, 14, 14)  # after 11:00 cutoff
        records = [
            _windfor("2026-01-15T12:00:00Z", after_pub.isoformat() + "Z", 9000),
        ]
        result = select_forecasts(records, {self.BASE_DELIVERY})
        assert self.BASE_DELIVERY not in result

    def test_no_forecasts_at_all(self):
        result = select_forecasts([], {self.BASE_DELIVERY})
        assert result == {}

    def test_duplicate_publish_time_handled(self):
        # Exact same publishTime twice → should still work without error
        pub = _utc(2026, 1, 14, 9)
        records = [
            _windfor("2026-01-15T12:00:00Z", pub.isoformat() + "Z", 9000),
            _windfor("2026-01-15T12:00:00Z", pub.isoformat() + "Z", 9000),
        ]
        result = select_forecasts(records, {self.BASE_DELIVERY})
        assert self.BASE_DELIVERY in result
        assert result[self.BASE_DELIVERY]["forecast_mw"] == pytest.approx(9000.0)

    def test_lead_time_calculation(self):
        """Lead time = delivery − publishTime in hours."""
        pub = _utc(2026, 1, 14, 9)  # 3 hours before cutoff
        delivery = _utc(2026, 1, 15, 12)
        expected_lead = (delivery - pub).total_seconds() / 3600  # 27h
        records = [_windfor("2026-01-15T12:00:00Z", pub.isoformat() + "Z", 9000)]
        result = select_forecasts(records, {delivery})
        assert result[delivery]["lead_time_h"] == pytest.approx(expected_lead, rel=1e-4)


# ---------------------------------------------------------------------------
# Tests: compute_metrics
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    """SYNTHETIC TEST DATA verified by hand calculation."""

    def _make_record(self, forecast, actual):
        """Build a minimal matched record (TEST DATA)."""
        return {
            "delivery_time": "2026-01-15T12:00:00",
            "forecast_mw":   forecast,
            "actual_mw":     actual,
            "error_mw":      forecast - actual,
            "publish_time":  "2026-01-14T08:00:00",
            "lead_time_h":   28.0,
            "cutoff":        "2026-01-14T11:00:00",
        }

    def test_mae(self):
        # errors: +200, -100 → MAE = (200 + 100) / 2 = 150
        records = [
            self._make_record(10200, 10000),
            self._make_record(9900,  10000),
        ]
        m = compute_metrics(records)
        assert m["mae_mw"] == pytest.approx(150.0)

    def test_rmse(self):
        # errors: +200, -100 → RMSE = sqrt((40000 + 10000)/2) = sqrt(25000) ≈ 158.11
        records = [
            self._make_record(10200, 10000),
            self._make_record(9900,  10000),
        ]
        m = compute_metrics(records)
        assert m["rmse_mw"] == pytest.approx(math.sqrt(25000), rel=1e-3)

    def test_bias_positive(self):
        # Overforecast: +500 each → bias = +500
        records = [self._make_record(10500, 10000)] * 3
        m = compute_metrics(records)
        assert m["bias_mw"] == pytest.approx(500.0)

    def test_bias_negative(self):
        # Underforecast
        records = [self._make_record(9500, 10000)] * 2
        m = compute_metrics(records)
        assert m["bias_mw"] == pytest.approx(-500.0)

    def test_mape_excluded_when_actual_zero(self):
        # actual = 0 → MAPE must not produce division by zero
        records = [self._make_record(100, 0)]
        m = compute_metrics(records)
        # Only zero-actual record; MAPE should be None or n_mape = 0
        assert m["n_mape"] == 0

    def test_empty_returns_none_metrics(self):
        m = compute_metrics([])
        assert m["mae_mw"] is None
        assert m["rmse_mw"] is None
        assert m["n"] == 0


# ---------------------------------------------------------------------------
# Tests: match_records and coverage
# ---------------------------------------------------------------------------

class TestMatchRecords:
    """SYNTHETIC TEST DATA."""

    STUDY_START = _utc(2026, 1, 1)
    STUDY_END   = _utc(2026, 1, 31, 23, 59, 59)

    def test_full_match(self):
        actuals = {_utc(2026, 1, 5, 6): 8000.0}
        cutoff  = _utc(2026, 1, 4, CUTOFF_HOUR_UTC)
        forecasts = {
            _utc(2026, 1, 5, 6): {
                "forecast_mw":  8500.0,
                "publish_time": _utc(2026, 1, 4, 9),
                "lead_time_h":  21.0,
                "cutoff":       cutoff,
            }
        }
        matched, coverage = match_records(actuals, forecasts, self.STUDY_START, self.STUDY_END)
        assert len(matched) == 1
        assert matched[0]["error_mw"] == pytest.approx(500.0)
        assert coverage["matched_count"] == 1
        assert coverage["missing_forecast_count"] == 0

    def test_missing_forecast(self):
        actuals = {_utc(2026, 1, 5, 6): 8000.0}
        matched, coverage = match_records(actuals, {}, self.STUDY_START, self.STUDY_END)
        assert len(matched) == 0
        assert coverage["missing_forecast_count"] == 1

    def test_missing_actual_is_counted_in_expected_study_hours(self):
        delivery = _utc(2026, 1, 1, 0)
        forecast = {delivery: {"forecast_mw": 100.0, "publish_time": _utc(2025, 12, 31, 9), "lead_time_h": 15.0, "cutoff": _utc(2025, 12, 31, 11)}}
        matched, coverage = match_records({}, forecast, delivery, delivery)
        assert matched == []
        assert coverage["missing_actual_count"] == 1

    def test_outside_study_period_excluded(self):
        # Record before study start should not appear
        actuals = {_utc(2025, 12, 31, 23): 5000.0}
        matched, coverage = match_records(actuals, {}, self.STUDY_START, self.STUDY_END)
        assert len(matched) == 0
        assert coverage["total_actual_hours"] == 0


# ---------------------------------------------------------------------------
# Tests: lead-time bands
# ---------------------------------------------------------------------------

class TestLeadTimeBands:
    """SYNTHETIC TEST DATA for lead-time band assignment."""

    def _make_record(self, lead_time_h):
        return {
            "delivery_time": "2026-01-15T12:00:00",
            "forecast_mw":   10000.0,
            "actual_mw":     10000.0,
            "error_mw":      0.0,
            "publish_time":  "2026-01-14T08:00:00",
            "lead_time_h":   lead_time_h,
            "cutoff":        "2026-01-14T11:00:00",
        }

    def test_24h_band(self):
        # lead ≥ 20h → ~24h band
        records = [self._make_record(25.0)]
        result = compute_lead_time_metrics(records)
        band_24 = next(b for b in result if "24h" in b["band"])
        assert band_24["count"] == 1

    def test_12h_band(self):
        # lead 10–20h → ~12h band
        records = [self._make_record(15.0)]
        result = compute_lead_time_metrics(records)
        band_12 = next(b for b in result if "12h" in b["band"])
        assert band_12["count"] == 1

    def test_lead_below_cutoff_minimum_is_not_in_any_day_ahead_band(self):
        # These bands describe forecasts selected at the documented cutoff.
        records = [self._make_record(5.0)]
        result = compute_lead_time_metrics(records)
        assert sum(b["count"] for b in result) == 0

    def test_empty_dataset(self):
        # Should return all bands with count=0 and no errors
        result = compute_lead_time_metrics([])
        assert len(result) == len(LEAD_TIME_BANDS)
        assert all(b["count"] == 0 for b in result)
