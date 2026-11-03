import csv, io, json, math, os, zipfile
import requests
import pandas as pd

GTFS_URL = "https://www.data.gouv.fr/api/1/datasets/r/5339d96c-6d20-4a01-939a-40f7b56d6cc1"

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def fetch_gtfs_zip(retries=4, backoff=5):
    import time
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(GTFS_URL, timeout=(15, 60))
            resp.raise_for_status()
            return zipfile.ZipFile(io.BytesIO(resp.content))
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"  GTFS download attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(f"Could not download GTFS after {retries} attempts") from last_error

def nearest_commune(lat, lon, communes):
    best_name, best_dist = None, None
    for c in communes:
        d = haversine_km(lat, lon, c["lat"], c["lon"])
        if best_dist is None or d < best_dist:
            best_dist, best_name = d, c["commune"]
    return best_name

def active_service_ids(day, calendar, calendar_dates):
    weekday_col = day.strftime("%A").lower()
    ymd = day.strftime("%Y%m%d")
    in_window = (calendar["start_date"] <= ymd) & (calendar["end_date"] >= ymd)
    active = set(calendar[in_window & (calendar[weekday_col] == "1")]["service_id"])
    exceptions = calendar_dates[calendar_dates["date"] == ymd]
    active |= set(exceptions[exceptions["exception_type"] == "1"]["service_id"])
    active -= set(exceptions[exceptions["exception_type"] == "2"]["service_id"])
    return active

def pick_representative_tuesday(calendar, calendar_dates, trips):
    trips_per_service = trips.groupby("service_id").size()
    start = pd.to_datetime(calendar["start_date"].min(), format="%Y%m%d")
    end = pd.to_datetime(calendar["end_date"].max(), format="%Y%m%d")
    best = None
    for day in pd.date_range(start, end, freq="W-TUE"):
        ids = active_service_ids(day, calendar, calendar_dates)
        n_trips = int(trips_per_service.reindex(list(ids)).fillna(0).sum())
        if best is None or n_trips > best[2]:
            best = (day, ids, n_trips)
    if best is None or best[2] == 0:
        raise RuntimeError("No Tuesday with scheduled trips -- feed structure may have changed")
    return best[0], best[1]

def build_commune_supply(freq, communes_df):
    """Supply-vs-demand proxy: scheduled stop-visits per 1,000 residents on the
    representative weekday. Population stands in for demand (no open ridership
    data exists); stops are attributed to the nearest commune *center*, not to
    real commune boundaries."""
    supply = freq.groupby("nearest_commune").agg(
        n_stops=("stop_id", "nunique"),
        daily_stop_visits=("daily_trip_count", "sum"),
        busiest_stop_visits=("daily_trip_count", "max"),
    ).reset_index().rename(columns={"nearest_commune": "commune"})
    supply = communes_df[["commune", "population"]].merge(supply, on="commune", how="left").fillna(0)
    for col in ["n_stops", "daily_stop_visits", "busiest_stop_visits"]:
        supply[col] = supply[col].astype(int)
    supply["visits_per_1000_residents"] = (supply["daily_stop_visits"] / supply["population"] * 1000).round(1)
    supply["stops_per_1000_residents"] = (supply["n_stops"] / supply["population"] * 1000).round(2)
    # Share of the commune's supply carried by its single busiest stop: a high
    # value flags communes whose score rests on one hub/terminus.
    supply["top_stop_share"] = (
        supply["busiest_stop_visits"] / supply["daily_stop_visits"].where(supply["daily_stop_visits"] > 0)
    ).round(2).fillna(0)
    supply = supply.sort_values("visits_per_1000_residents", ascending=False).reset_index(drop=True)
    supply.insert(0, "rank", supply.index + 1)
    return supply

def main():
    communes_df = pd.read_csv("data/reference/communes.csv")
    communes = communes_df.to_dict("records")

    print("Downloading SETRAM static GTFS feed...")
    zf = fetch_gtfs_zip()

    # dtype=str throughout: stop_id/route_id/trip_id mix numeric-looking and
    # non-numeric values (e.g. "FLEX-381") across GTFS files -- letting pandas
    # infer dtypes per-file causes silent int64-vs-object merge failures.
    routes = pd.read_csv(zf.open("routes.txt"), dtype=str)
    stops = pd.read_csv(zf.open("stops.txt"), dtype=str)
    trips = pd.read_csv(zf.open("trips.txt"), dtype=str)
    calendar = pd.read_csv(zf.open("calendar.txt"), dtype=str)
    stop_times = pd.read_csv(zf.open("stop_times.txt"), usecols=["trip_id", "stop_id"], dtype=str)
    stops["stop_lat"] = stops["stop_lat"].astype(float)
    stops["stop_lon"] = stops["stop_lon"].astype(float)
    print(f"Loaded {len(routes)} routes, {len(stops)} stops, {len(trips)} trips, {len(stop_times)} stop_times")

    calendar_dates = pd.read_csv(zf.open("calendar_dates.txt"), dtype=str)

    # Pick a representative weekday: the Tuesday with the most scheduled trips,
    # counting *every* service_id active that day. Picking a single service_id
    # (as the original version did) silently drops whole modes: SETRAM puts
    # buses and trams in separate service_ids with identical validity windows,
    # so a "longest window" tie-break kept buses only and lost T1/T2.
    rep_date, service_ids = pick_representative_tuesday(calendar, calendar_dates, trips)
    print(f"Using Tuesday {rep_date:%Y-%m-%d} as the representative weekday "
          f"({len(service_ids)} active service_ids: {sorted(service_ids)})")

    weekday_trip_ids = set(trips[trips["service_id"].isin(service_ids)]["trip_id"])
    weekday_stop_times = stop_times[stop_times["trip_id"].isin(weekday_trip_ids)]

    freq = weekday_stop_times.groupby("stop_id").size().reset_index(name="daily_trip_count")
    freq = freq.merge(
        stops[["stop_id", "stop_name", "stop_lat", "stop_lon", "wheelchair_boarding"]],
        on="stop_id", how="left",
    ).dropna(subset=["stop_lat"])

    print(f"Assigning {len(freq)} stops to nearest of {len(communes)} communes...")
    freq["nearest_commune"] = freq.apply(
        lambda row: nearest_commune(row["stop_lat"], row["stop_lon"], communes), axis=1
    )

    freq = freq.sort_values("daily_trip_count", ascending=False)
    os.makedirs("data/gtfs_static", exist_ok=True)
    freq.to_csv("data/gtfs_static/stops_frequency.csv", index=False)
    routes[["route_id", "route_short_name", "route_long_name", "route_type"]].to_csv(
        "data/gtfs_static/routes.csv", index=False
    )
    print(f"Wrote data/gtfs_static/stops_frequency.csv ({len(freq)} rows)")
    print(f"Wrote data/gtfs_static/routes.csv ({len(routes)} rows)")
    print("Top 5 busiest stops:")
    print(freq[["stop_name", "daily_trip_count", "nearest_commune"]].head(5).to_string(index=False))

    supply = build_commune_supply(freq, communes_df)
    supply.to_csv("data/gtfs_static/commune_supply.csv", index=False)
    # Validity of the timetable actually used, not calendar.txt's overall max:
    # on-demand FLEX services can outlive the regular bus/tram timetable.
    used = calendar[calendar["service_id"].isin(service_ids)]
    valid_until = pd.to_datetime(used["end_date"], format="%Y%m%d").max()
    os.makedirs("docs/data", exist_ok=True)
    with open("docs/data/commune_supply.json", "w", encoding="utf-8") as f:
        json.dump({
            "representative_date": f"{rep_date:%Y-%m-%d}",
            "feed_valid_until": f"{valid_until:%Y-%m-%d}",
            "metric": "Scheduled stop-visits per 1,000 residents on a representative weekday",
            "communes": supply.to_dict("records"),
        }, f, indent=2, ensure_ascii=False)
    print(f"Wrote data/gtfs_static/commune_supply.csv and docs/data/commune_supply.json ({len(supply)} communes)")
    print(supply[["rank", "commune", "population", "n_stops", "daily_stop_visits",
                  "visits_per_1000_residents", "top_stop_share"]].to_string(index=False))

if __name__ == "__main__":
    main()
