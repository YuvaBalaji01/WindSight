# WindSight UK 💨

**Wind Generation Forecast Accuracy Dashboard for UK Electricity Procurement**

A full-stack analytics platform that measures day-ahead wind forecast accuracy using
real data from Elexon BMRS — comparing WINDFOR (hourly wind generation forecasts)
against FUELHH (half-hourly actual fuel-mix generation) for January 2026.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Design Decisions](#design-decisions)
3. [Quick Start — Local Development](#quick-start--local-development)
4. [Docker Deployment](#docker-deployment)
5. [API Reference](#api-reference)
6. [Running Tests](#running-tests)
7. [Project Structure](#project-structure)

---

## Architecture Overview

```
┌─────────────────────┐        HTTP/JSON        ┌────────────────────────────┐
│  React Frontend      │  ◄──────────────────►  │  FastAPI Backend           │
│  (Vite + Recharts)   │                         │  (Python 3.12 + Uvicorn)   │
│  port 5173 (dev)     │                         │  port 8000                 │
│  port 80   (Docker)  │                         │                            │
└─────────────────────┘                         │  ┌─────────────────────┐   │
                                                 │  │   analytics.py      │   │
                              Elexon BMRS API    │  │  (pure-Python, no   │   │
                              ──────────────►    │  │   pandas/numpy)     │   │
                              FUELHH  / WINDFOR  │  └─────────────────────┘   │
                                                 │  ┌─────────────────────┐   │
                                                 │  │   backend/cache/    │   │
                                                 │  │   (JSON disk cache) │   │
                                                 │  └─────────────────────┘   │
                                                 └────────────────────────────┘
```

---

## Design Decisions

### 1. Granularity Alignment (FUELHH → hourly actuals)

FUELHH provides **30-minute** half-hourly generation readings (MW).  
WINDFOR provides **hourly** forecast generation readings (MW).

To compare on the same axis both the 00:00 and 00:30 half-hours are averaged
into a single hourly MW figure. This is correct because MW is an instantaneous
rate, not cumulative energy — the arithmetic mean of two half-hour MW readings
gives the representative MW for that hour.

### 2. Day-ahead Decision Cutoff — 11:00 UTC

The application uses an explicit assumed decision cutoff of 11:00 UTC on the
previous calendar day. This modeling rule has not been validated against a
specific procurement auction or buyer contract. January is GMT, so:

```
cutoff(delivery_date) = (delivery_date − 1 day) at 11:00 UTC
```

Example: for delivery on `2026-01-15 14:00 UTC`, the cutoff is `2026-01-14 11:00 UTC`.

Only WINDFOR publications with `publishTime ≤ cutoff` are eligible. The **latest**
such publication is selected (most up-to-date information the buyer had).

### 3. Error Convention

```
error_mw = forecast_mw − actual_mw
```
- Positive → overforecast (forecast exceeded actual generation)
- Negative → underforecast (forecast underestimated actual generation)

### 4. Lead-time Bands

| Band | Lead Time |
|------|-----------|
| ~24h | ≥ 20 h before delivery |
| ~12h | 10 – 20 h before delivery |

The selected day-ahead forecast cannot be less than 10 hours ahead of delivery
under this cutoff. These groups compare lead times of selected forecasts; they
are not fixed-lead comparisons and do not measure later intraday forecast accuracy.

### 5. MAPE — Zero Actual Exclusion

MAPE is undefined when `actual_mw = 0`. Such intervals are excluded from MAPE
and the excluded count is reported in `n_mape`.

### 6. Caching Strategy

Elexon API responses are cached to `backend/cache/*.json` to avoid re-fetching
~31 days of 30-min data on every request. Cache is bypassed with `?refresh=true`.
In Docker, the cache is mounted as a named volume so it persists across container
restarts.

---

## Quick Start — Local Development

### Prerequisites

- Python 3.11+ with `venv`
- Node 20+

### Backend

```bash
cd backend

# Create & activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start API server (auto-reload on code changes)
uvicorn main:app --reload --port 8000
```

> **First run:** On the first API call the backend fetches ~31 days of FUELHH
> and WINDFOR records from Elexon BMRS (~20–60 seconds). Subsequent calls use
> the file cache and respond in milliseconds.

Open `http://localhost:8000/docs` for the interactive Swagger UI.

### Frontend

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173` to view the dashboard.

---

## Docker Deployment

### Build and start all services

```bash
docker compose up --build
```

- Frontend: `http://localhost` (port 80)
- Backend API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`

### Subsequent starts (images already built)

```bash
docker compose up -d
```

### Stop

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # stop + remove volumes (clears cache)
```

### Remote deployment

Change `VITE_API_BASE_URL` in `docker-compose.yml` to your server's public IP
or hostname before building:

```yaml
args:
  VITE_API_BASE_URL: "https://api.your-domain.com"
```

---

## API Reference

All endpoints are read-only (`GET`).

### `GET /api/health`
Returns `{"status": "healthy"}` for liveness checks.

### `GET /api/overview`
Project metadata, cutoff policy, and endpoint index.

### `GET /api/forecast-accuracy/summary`

Monthly summary metrics + coverage.

| Query param | Default | Description |
|---|---|---|
| `from` | `2026-01-01` | Start date (YYYY-MM-DD), inclusive |
| `to` | `2026-01-31` | End date (YYYY-MM-DD), inclusive |
| `refresh` | `false` | Force re-fetch from Elexon API |

The API calculates metrics from the Elexon records available to the backend;
it does not use canned sample metrics. Coverage includes matched, expected,
missing actual, and missing forecast counts.

### `GET /api/forecast-accuracy`

Per-interval detail for a single delivery date.

| Query param | Required | Description |
|---|---|---|
| `date` | ✅ | Delivery date (YYYY-MM-DD) |
| `refresh` | ❌ | Force re-fetch |

### `GET /api/forecast-accuracy/lead-times`

Accuracy metrics broken down by lead-time band.

| Query param | Default | Description |
|---|---|---|
| `from` | `2026-01-01` | Start date |
| `to` | `2026-01-31` | End date |
| `refresh` | `false` | Force re-fetch |

---

## Running Tests

```bash
cd backend
# Activate venv first (see Quick Start)
pip install -r requirements-dev.txt
pytest -v
```

All 28 unit tests cover:
- `build_hourly_actuals` — aggregation, edge-cases, malformed records
- `cutoff_for_delivery` — standard days, midnight, month boundaries
- `select_forecasts` — cutoff filtering, latest-selection, lead-time calc
- `compute_metrics` — MAE, RMSE, bias, MAPE, zero-actual exclusion
- `match_records` — full/partial match, study-period exclusion
- `compute_lead_time_metrics` — band assignment and empty datasets

---

## Project Structure

```
Gridbricks assn/
├── docker-compose.yml          # Orchestrates backend + frontend
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── main.py                 # FastAPI app, CORS, entry point
│   ├── routes.py               # API route definitions
│   ├── ingestion.py            # Elexon BMRS API client + caching
│   ├── analytics.py            # Core analytics engine (pure Python)
│   ├── pytest.ini
│   ├── tests/
│   │   └── test_analytics.py   # 26 unit tests
│   └── cache/                  # Auto-created JSON cache (git-ignored)
│
└── frontend/
    ├── Dockerfile              # Two-stage: Vite build → nginx
    ├── nginx.conf              # SPA routing + cache headers
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx             # Dashboard UI components
        ├── api.js              # Typed API client
        ├── index.css           # Dark theme design system
        └── App.css

See [SUBMISSION_GUIDE.md](SUBMISSION_GUIDE.md) for recording prompts and the
remaining publication and verification steps.
```

---

## Data Sources

| Dataset | Endpoint | Description |
|---|---|---|
| **FUELHH** | [`GET /datasets/FUELHH/stream`](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream) | Half-hourly actual fuel-mix generation (MW), filtered with `fuelType=WIND`; uses `startTime` and `generation` |
| **WINDFOR** | [`GET /datasets/WINDFOR/stream`](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream) | Wind generation forecasts (MW); queries `publishDateTimeFrom` / `publishDateTimeTo`; uses `startTime`, `publishTime`, and `generation` |

Both datasets are sourced from the **Elexon BMRS REST API** (Balancing Mechanism Reporting Service), the authoritative source for UK electricity settlement and system data.

Study period: **January 2026 (2026-01-01 → 2026-01-31 UTC)**

## Environment variables

| Variable | Used by | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | Frontend build | Absolute backend API URL. Defaults to `http://localhost:8000` only in Vite development. Required for a separate production frontend. |
| `CORS_ORIGINS` | Backend runtime | Comma-separated allowed browser origins. Defaults to `http://localhost:5173`; Compose configures local origins. |

No Elexon credentials are required. Do not add secrets to Vite variables; they
are embedded in browser assets.

## Limitations and submission status

- The dashboard evaluates the latest WINDFOR publication available at the
  configured previous-day cutoff. It does not evaluate later intraday vintages
  or fixed lead-time snapshots.
- FUELHH half-hour values are averaged to hourly mean MW only when both
  half-hours are present. Incomplete hours are excluded and counted as missing.
- Cached January records are included in this workspace for repeatable local
  review. A deployment without the cache needs network access to Elexon.
- No public deployment URL, public GitHub URL, or YouTube URL is configured or
  verified. Do not submit placeholder links.
- No screenshot has been captured for this README.
- AI disclosure: OpenAI Codex was used to review and modify the code and
  documentation. The project owner should confirm this wording is complete.

### Deployment configuration

Only local Docker configuration is present. The project has no Vercel or
Heroku deployment configuration. Deploy the frontend and FastAPI backend to
public services, set `VITE_API_BASE_URL` to the backend URL at frontend build
time, and configure backend `CORS_ORIGINS` with the public frontend origin.
Then verify both URLs and API-backed January results in a private browser
session, and add the verified URLs here.

### Demo recording checklist

Record one unlisted YouTube video of at most 10 minutes with two sections:

1. Client presentation (up to 5 minutes): procurement context, dashboard,
   forecast versus actuals, metrics, coverage, and limitations.
2. Technical review (up to 5 minutes): architecture, Elexon endpoints and
   cutoff selection, analytics/tests, Docker, and deployment status. Show only
   deployment details that have been verified.

Upload as **Unlisted**, verify the link in a signed-out/private browser, and
enter it in the submission form. The Microsoft form has not been submitted.
