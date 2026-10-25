# WindSight UK

**Wind generation forecast accuracy dashboard for UK day-ahead electricity procurement.**

WindSight helps a day-ahead power buying team answer two questions:

1. **What was the latest wind forecast available at the moment the purchase decision had to be made?**
2. **How accurate are those forecasts, quantitatively?** (MAE, RMSE, bias, MAPE, lead time, data coverage)

It compares Elexon **WINDFOR** (wind forecasts) against **FUELHH** (actual wind generation, `fuelType=WIND`) at national level for **January 2026**. No other data is used.

---

## Links

| Item | URL |
|---|---|
| Live app (Vercel frontend) | https://wind-sight-7zxp.vercel.app/ |
| Backend API (health check) | `<BACKEND_URL>/api/health` ← replace with your deployed backend URL |
| Demo video | https://drive.google.com/file/d/1Dv1GXEfMYnPMV3giywHJQzgZzerJIHt7/view?usp=sharing |

---

## AI tools disclosure

AI tools (OpenAI Codex) were used to assist with reviewing and modifying the code and documentation. All logic, assumptions and results were reviewed by the author.

---

## Repository layout

```
.
├── docker-compose.yml        # Runs backend + frontend together
├── README.md
├── backend/                  # Python (FastAPI)
│   ├── Dockerfile
│   ├── requirements.txt      # runtime dependencies
│   ├── requirements-dev.txt  # test dependencies (pytest)
│   ├── pytest.ini
│   ├── main.py               # App setup, CORS, health + overview endpoints
│   ├── routes.py             # Accuracy API endpoints, in-memory result cache
│   ├── ingestion.py          # Elexon BMRS client, validation, de-duplication, JSON file cache
│   ├── analytics.py          # Alignment, cutoff logic, forecast selection, metrics
│   └── tests/
│       └── test_analytics.py # 28 unit tests for the analytics engine
└── frontend/                 # React (Vite + Recharts)
    ├── Dockerfile            # Vite build, served by nginx
    ├── nginx.conf
    ├── package.json
    ├── vite.config.js
    ├── .env.example          # VITE_API_BASE_URL
    └── src/
        ├── main.jsx
        ├── App.jsx           # Dashboard UI (simple + detailed views, charts, table, CSV export)
        ├── api.js            # API client
        ├── index.css
        └── App.css
```

---

## How the analysis works

### Data

| Dataset | Used for | Fields |
|---|---|---|
| FUELHH (`fuelType=WIND`) | Actual generation, 30-minute resolution | `startTime`, `generation` |
| WINDFOR | Forecast generation | `startTime`, `publishTime`, `generation` |

Scope: delivery hours from **2026-01-01 00:00 UTC to 2026-01-31 23:00 UTC**. WINDFOR publications are fetched from 2025-12-25 so that day-ahead forecasts for early-January delivery are available.

### Decision rule (what the buyer could have seen)

For every delivery hour, the app picks the **latest WINDFOR publication with `publishTime` ≤ 11:00 UTC on the previous day**. That is the forecast a buyer would have had when placing the day-ahead order.

```
cutoff(delivery) = (delivery date − 1 day) at 11:00 UTC      # January is GMT, so UTC = UK time
```

> The 11:00 UTC cutoff is an **explicit modelling assumption**, not a validated rule for a specific market or contract. It is a single constant (`CUTOFF_HOUR_UTC` in `backend/analytics.py`) and should be confirmed with the client.

### Granularity alignment

FUELHH is half-hourly; the forecast is compared at hourly level. The two half-hour readings in an hour are averaged (MW is a rate, so the mean is the hourly MW). **Hours with only one half-hour present are excluded** and counted as missing, not silently filled.

### Error convention and metrics

```
error_mw = forecast_mw − actual_mw
```

Positive means over-forecast, negative means under-forecast.

| Metric | Meaning |
|---|---|
| MAE | Average absolute error (MW) |
| RMSE | Error size with large misses weighted more heavily (MW) |
| Bias | Average signed error (MW); persistent over/under-forecasting |
| MAPE | Average absolute % error; **hours with zero actual generation are excluded** and the number used is reported (`n_mape`) |
| Coverage | Matched hours vs expected hours, plus counts of missing actuals and missing forecasts |

### Lead-time bands

Lead time = delivery hour − publish time. Because of the cutoff, selected forecasts are always at least ~10 hours ahead. Two bands are reported: `≥20h` and `10–20h`. These describe the forecast that was selected under the cutoff rule. They are **not** a fixed-horizon forecast comparison.

---

## Running the application

### Option 1: Docker (recommended)

```bash
docker compose up --build
```

- Frontend: http://localhost
- Backend API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs

Stop with `docker compose down` (add `-v` to also delete the cached Elexon data volume).

### Option 2: Local development

**Backend** (Python 3.11+)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend** (Node 20+)

```bash
cd frontend
cp .env.example .env.local      # VITE_API_BASE_URL=http://localhost:8000
npm ci
npm run dev
```

Open http://localhost:5173.

> **First request is slow.** On first use the backend downloads January data from Elexon (roughly 20 to 60 seconds). Results are then cached to `backend/cache/` and in memory. On hosts with an ephemeral filesystem the cache is lost on restart, so the first request after a cold start is slow again.

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -v
```

28 unit tests cover hourly aggregation, cutoff calculation, forecast selection, all metrics (including the zero-actual MAPE rule), record matching and lead-time bands.

---

## API reference

All endpoints are `GET`. Dates are `YYYY-MM-DD` and must fall within January 2026.

| Endpoint | Parameters | Returns |
|---|---|---|
| `/api/health` | none | `{"status": "healthy"}` |
| `/api/overview` | none | Dataset names, period, cutoff policy, endpoint index |
| `/api/forecast-accuracy/summary` | `from`, `to`, `refresh` | Overall MAE/RMSE/bias/MAPE and coverage for the range |
| `/api/forecast-accuracy` | `date` (required), `refresh` | Per-hour forecast, actual, error, publish time, lead time for one delivery day |
| `/api/forecast-accuracy/lead-times` | `from`, `to`, `refresh` | Metrics per lead-time band |

`refresh=true` forces a re-fetch from Elexon instead of using the cache.

---

## Configuration

| Variable | Used by | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | Frontend (build time) | Backend URL. Defaults to `http://localhost:8000` in dev. Required for a deployed frontend. |
| `FRONTEND_ORIGINS` | Backend (runtime) | Comma-separated extra browser origins allowed by CORS (for example your Vercel URL). |

No Elexon credentials or secrets are needed.

---

## Deployment

- **Frontend:** Vercel, project root `frontend/`, with `VITE_API_BASE_URL` set to the backend's HTTPS URL.
- **Backend:** FastAPI service, start command `uvicorn main:app --host 0.0.0.0 --port $PORT` from `backend/`. It needs outbound access to `data.elexon.co.uk`, and `FRONTEND_ORIGINS` must include the frontend origin.

---

## Limitations

- Evaluates the latest forecast available at the assumed previous-day cutoff only. It does not evaluate later intraday forecast updates or fixed-horizon forecasts.
- The cutoff time is an assumption to be validated with the buyer.
- Scope is national wind only, January 2026 delivery days, from Elexon data alone.
- Accuracy metrics describe past performance and do not guarantee future forecast error.