# WindSight UK submission guide

## Recording plan (target: 8 minutes 30 seconds)

Record one unlisted video with two chapters. Keep each chapter under five
minutes and the complete video under ten minutes. Use the local app until a
public deployment exists; clearly state that deployment is pending.

### Part 1 — Client presentation (4:15 maximum)

- **0:00–0:40 — Business problem:** “A procurement team buying day-ahead
  electricity needs to know what wind generation forecast was available at
  its decision point, then compare that forecast with actual generation to
  understand forecast error.”
- **0:40–1:25 — Scope:** “This dashboard uses national UK wind data from
  Elexon FUELHH actuals and WINDFOR forecasts for January 2026. The charts
  show hourly MW. Two complete FUELHH half-hours are averaged for each hour.”
- **1:25–2:20 — Dashboard:** Show the January summary cards, select a date,
  and point out the forecast and actual series. Hover a point to show the
  interval and compare the error chart with the detail table.
- **2:20–3:15 — Accuracy:** “MAE is the average absolute error, RMSE weighs
  larger misses more heavily, and bias is forecast minus actual. Positive
  bias means overforecasting; negative bias means underforecasting. MAPE
  excludes zero-actual intervals.” Point to the live values and sample counts.
- **3:15–3:50 — Decision relevance:** “The selected value is the latest
  WINDFOR publication at or before 11:00 UTC on the day before delivery.
  Publication time and lead time are retained for each matched hour.”
- **3:50–4:15 — Limits:** “This is a historical forecast-accuracy view. The
  11:00 UTC cutoff is an explicit modeling assumption to validate with the
  buyer. Lead-time bands describe selected forecasts; they are not a
  comparison of fixed forecast horizons, and later intraday accuracy is not
  measured.”

### Part 2 — Technical review (4:15 maximum)

- **0:00–0:40 — Architecture:** Show the React/Vite dashboard calling the
  FastAPI backend. Explain that analytics, ingestion, and API routes are
  separated into their own modules.
- **0:40–1:25 — Ingestion:** Show `backend/ingestion.py`. Explain the FUELHH
  date/fuel filters and WINDFOR publication-time window, JSON response
  validation, cache, and retained publication timestamps.
- **1:25–2:10 — Selection and alignment:** Show `backend/analytics.py`.
  Explain pair-complete half-hour aggregation, prior-day cutoff, latest
  eligible forecast selection, timestamp matching, and explicit missing
  interval counts.
- **2:10–2:55 — Metrics and tests:** Explain MAE, RMSE, bias, MAPE, lead time,
  and zero-actual handling. From `backend`, run `pip install -r requirements-dev.txt`
  and `python -m pytest -v`. State the observed result.
- **2:55–3:30 — Frontend/API:** Show the date filter, live API response, and
  CSV export. Mention health, summary, day-detail, and lead-time endpoints.
- **3:30–4:15 — Docker and release:** Show the Dockerfiles and Compose file.
  State truthfully that image build/startup has not been verified because the
  Docker daemon was unavailable. Explain that public deployment, repository,
  and incognito link checks remain pending; do not show placeholder URLs.

## Manual publish and verification steps

1. Create a public GitHub repository using a random, non-identifying name.
   Confirm `.env.local`, `node_modules`, virtual environments, `dist`, and
   backend cache files are excluded. This workspace currently has no Git
   repository or remote.
2. Deploy the frontend to Vercel with the frontend directory as the project
   root and set `VITE_API_BASE_URL` to the deployed backend's HTTPS URL.
3. Deploy the FastAPI backend to Heroku or another publicly accessible Python
   service. Start it with `uvicorn main:app --host 0.0.0.0 --port $PORT` from
   the `backend` directory. Set `CORS_ORIGINS` to the exact frontend origin.
   Ensure outbound access to `data.elexon.co.uk` is available.
4. Open the public frontend and backend `/api/health` and January summary URLs
   in a fresh private/incognito browser window. Confirm the browser console
   has no CORS or localhost errors and the dashboard displays returned data.
5. Record the two video sections above, upload the complete video to YouTube
   as **Unlisted**, and verify playback while signed out or in a private
   window. Confirm total duration is at most 10 minutes.
6. Open the [assignment submission form](https://forms.cloud.microsoft/r/FTX6K2bbnU)
   in a private window, enter the verified public
   GitHub, frontend, and YouTube URLs, and submit. Confirm the completion
   message. The form has not been submitted by this audit.
