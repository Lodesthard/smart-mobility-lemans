# Smart Mobility Le Mans

Decision-support pipeline for Le Mans Métropole's SETRAM bus and tram network:

> If Le Mans Métropole had limited resources to improve its public transport network,
> where and when should it prioritize interventions?

## Pipelines

| Workflow | Schedule | Script | Output |
|---|---|---|---|
| Build static reference | 04:00 UTC on the 1st of each month + manual | `scripts/build_static_reference.py` | `data/gtfs_static/stops_frequency.csv`, `routes.csv`, `commune_supply.csv`, `docs/data/commune_supply.json` |
| Collect realtime snapshot | every 15 minutes | `scripts/collect_snapshot.py` | `data/history/route_delays_YYYY-MM.csv`, `alerts_log.csv`, `docs/data/current_state.json` |

The dashboard (`docs/index.html`, served by GitHub Pages from `/docs`) shows the live
network status and the commune supply-vs-population ranking.

## Sources

- Static GTFS (SETRAM, via data.gouv.fr): routes, stops, scheduled trips.
- GTFS-RT TripUpdate and Service Alert (SETRAM, via transport.data.gouv.fr proxy).
- `data/reference/communes.csv`: INSEE legal population of the 20 communes, centers
  geocoded with the French national address API.

## Changes from the course template

- **Representative weekday.** The template kept a single `service_id` (the Tuesday
  pattern with the longest validity window). SETRAM splits buses and trams into
  separate `service_id`s with identical windows, so the tie-break silently dropped
  tram lines T1/T2. The script now takes every service active on the busiest Tuesday
  of the feed (`calendar.txt` + `calendar_dates.txt`): 1,011 stops instead of 798.
- **Supply vs. population.** Computed in the monthly static workflow, since it only
  changes when the timetable does. Metric: scheduled stop-visits per 1,000 residents.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install requests pandas gtfs-realtime-bindings
.venv/Scripts/python scripts/build_static_reference.py
.venv/Scripts/python scripts/collect_snapshot.py
python -m http.server -d docs 8000   # then open http://localhost:8000
```

On Windows, set `PYTHONUTF8=1` so alert texts with accents are written correctly.
