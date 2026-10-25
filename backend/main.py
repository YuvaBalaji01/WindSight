"""
main.py
=======
WindSight UK – FastAPI application entry point.

Run locally:
  cd backend
  uvicorn main:app --reload --port 8000

CORS origins are configured via the CORS_ORIGINS environment variable
(comma-separated list).  Falls back to localhost:5173 for local development.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="WindSight UK API",
    description=(
        "Wind generation forecast accuracy for UK electricity procurement. "
        "Data sourced from Elexon BMRS (FUELHH + WINDFOR), January 2026."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
allowed_origins = [
    "http://localhost:5173",
    "https://wind-sight-blush.vercel.app",
    "https://wind-sight-git-main-yuvabalaji01s-projects.vercel.app",
]

extra_origins = os.getenv("FRONTEND_ORIGINS", "")
allowed_origins.extend(
    origin.strip().rstrip("/")
    for origin in extra_origins.split(",")
    if origin.strip()
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(allowed_origins)),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(router)


@app.get("/")
def home():
    return {"message": "WindSight UK backend is running", "version": "1.0.0"}


@app.get("/api/health")
def health():
    return {"status": "healthy"}


@app.get("/api/overview")
def overview():
    return {
        "project":          "WindSight UK",
        "actual_dataset":   "FUELHH",
        "forecast_dataset": "WINDFOR",
        "fuel_type":        "WIND",
        "period":           "January 2026",
        "cutoff_policy":    "Assumed day-ahead cutoff: 11:00 UTC on delivery date − 1 day",
        "endpoints": {
            "health":          "/api/health",
            "overview":        "/api/overview",
            "day_detail":      "/api/forecast-accuracy?date=2026-01-15",
            "monthly_summary": "/api/forecast-accuracy/summary?from=2026-01-01&to=2026-01-31",
            "lead_times":      "/api/forecast-accuracy/lead-times?from=2026-01-01&to=2026-01-31",
        },
    }
