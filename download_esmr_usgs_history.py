#!/usr/bin/env python3
"""
Roseville-Area Monitoring Data from eSMR and USGS
=================================================
Downloads two more sources of historical creek data for the dashboard's Historical
Analysis tab (CEDEN is handled by download_roseville_ceden_history.py):

1. eSMR (Electronic Self-Monitoring Reports) - State Water Resources Control Board,
   https://data.ca.gov/dataset/water-quality-effluent-electronic-self-monitoring-report-esmr-data
   Wastewater plants with discharge permits must measure the creek they discharge into.
   The City of Roseville runs two plants that do this:
     - Dry Creek WWTP (facility 220768) on Dry Creek
     - Pleasant Grove WWTP (facility 248706) on Pleasant Grove Creek (a different watershed)
   Each has two "receiving water" stations:
     RSW-001 ~200 ft upstream of the discharge (normal creek conditions)
     RSW-002 ~200 ft downstream of the discharge (affected by treated wastewater)
   Note: eSMR has no coordinates for these stations, so approximate ones are used for maps.
   eSMR also labels the Dry Creek plant's creek "in the Russian River Watershed"; that is a
   data-entry error (the record is filed under Region 5S - Sacramento).

2. USGS (U.S. Geological Survey)
     - Daily stream flow from gauges in the Dry Creek Watershed (waterservices.usgs.gov)
     - Field water quality samples at USGS sites in the watershed (Water Quality Portal,
       waterqualitydata.us)

Usage in VS Code Terminal:
    python3 download_esmr_usgs_history.py            # both sources
    python3 download_esmr_usgs_history.py esmr       # only eSMR (takes ~5-10 minutes)
    python3 download_esmr_usgs_history.py usgs       # only USGS (under a minute)

Saves new dated files (never overwrites earlier downloads):
    Raw_data/esmr/roseville_wwtp_esmr_YYYY-MM-DD.csv.gz
    Raw_data/usgs/dry_creek_usgs_YYYY-MM-DD.csv.gz
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd

USER_AGENT = "DryCreekConservancyDashboard/2.0"
BASE_DIR = Path(__file__).parent
ESMR_DIR = BASE_DIR / "Raw_data" / "esmr"
USGS_DIR = BASE_DIR / "Raw_data" / "usgs"

# every historical source is saved / loaded with these columns
UNIFIED_COLUMNS = [
    "Source", "Agency", "StationCode", "StationName", "StationNote", "Creek", "Watershed",
    "SampleDate", "SampleTime", "Parameter", "Analyte", "Unit", "Result", "ResultQualifier",
    "DataQuality", "Latitude", "Longitude", "LocationApproximate",
]

SOURCE_CEDEN = "CEDEN (State Water Board)"
SOURCE_ESMR_DRY = "eSMR: Roseville Dry Creek WWTP"
SOURCE_ESMR_PG = "eSMR: Roseville Pleasant Grove WWTP"
SOURCE_USGS = "USGS"

# ---------------------------------------------------------------------------- eSMR
ESMR_PACKAGE = "water-quality-effluent-electronic-self-monitoring-report-esmr-data"
ESMR_FACILITIES = {
    220768: {
        "source": SOURCE_ESMR_DRY, "agency": "City of Roseville (Dry Creek WWTP)",
        "creek": "Dry Creek", "watershed": "Dry Creek",
        # approximate: CEDEN's "Dry Creek at Roseville WWTP" station (eSMR has no coordinates)
        "lat": 38.7341, "lon": -121.3144,
    },
    248706: {
        "source": SOURCE_ESMR_PG, "agency": "City of Roseville (Pleasant Grove WWTP)",
        "creek": "Pleasant Grove Creek", "watershed": "Pleasant Grove Creek",
        # approximate: CEDEN's Pleasant Grove Creek receiving-water site near the plant
        "lat": 38.7948, "lon": -121.3725,
    },
}
ESMR_STATION_NOTES = {
    "RSW-001": "~200 ft upstream of the wastewater discharge",
    "RSW-002": "~200 ft downstream of the wastewater discharge (affected by treated wastewater)",
}
ESMR_PARAMETERS = {
    # eSMR parameter name -> (dashboard parameter, accepted units)
    "Dissolved Oxygen": ("DO", ["mg/L"]),
    "Electrical Conductivity @ 25 Deg. C": ("SPC", ["umhos/cm", "uS/cm"]),
    "Specific Conductance": ("SPC", ["umhos/cm", "uS/cm"]),
    "pH": ("PH", ["SU", "pH units"]),
    "Temperature": ("Water Temp", ["Degrees C", "Degrees F"]),
    "Turbidity": ("Turbidity", ["NTU"]),
}
ESMR_COLUMNS = [
    "facility_place_id", "facility_name", "location", "location_desc", "parameter", "units",
    "qualifier", "result", "sampling_date", "sampling_time", "review_priority_indicator", "qa_codes",
]

# ---------------------------------------------------------------------------- USGS
USGS_FLOW_SITES = {
    # site number -> (name, creek); all inside the Dry Creek Watershed
    "11447293": ("Dry Creek at Vernon St Bridge at Roseville", "Dry Creek"),
    "11447270": ("Miners Ravine near Loomis", "Miners Ravine"),
    "11447300": ("Dry Creek Tributary near Roseville", "Dry Creek"),
}
# Dry Creek Watershed box (same as the CEDEN downloader) for finding USGS water quality sites
BBOX = (-121.48, 38.64, -121.08, 38.90)
USGS_WQ_NAME_TO_CREEK = {
    "DRY C": "Dry Creek", "MINERS RAVINE": "Miners Ravine", "SECRET RAVINE": "Secret Ravine",
    "ANTELOPE C": "Antelope Creek", "LINDA C": "Linda Creek", "CIRBY C": "Cirby Creek",
    "CLOVER VALLEY": "Clover Valley Creek", "STRAP RAVINE": "Strap Ravine",
}
USGS_WQ_CHARACTERISTICS = {
    "Dissolved oxygen (DO)": "DO", "Specific conductance": "SPC", "pH": "PH",
    "Temperature, water": "Water Temp", "Turbidity": "Turbidity",
}


def _get(url: str, timeout: int = 180, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {exc.code}: {body}"
            if exc.code in (400, 404, 409) and "too long" not in body.lower():
                raise RuntimeError(last) from None
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(last)


def _ckan(path: str, timeout: int = 180) -> dict:
    return json.loads(_get(f"https://data.ca.gov/api/3/action/{path}", timeout=timeout).decode("utf-8"))


# ---------------------------------------------------------------------------- eSMR download
def esmr_year_tables() -> list[dict]:
    """Yearly eSMR tables (skips the bulk all-years files)."""
    res = _ckan(f"package_show?id={ESMR_PACKAGE}", timeout=30)["result"]["resources"]
    out = []
    for r in res:
        name = r.get("name", "")
        if r.get("datastore_active") and name[:4].isdigit() and "Present" not in name:
            out.append({"name": name, "id": r["id"], "year": name[:4]})
    return sorted(out, key=lambda t: t["year"])


def fetch_esmr_table(resource_id: str, facility_ids: list[int]) -> pd.DataFrame:
    cols = ", ".join(f'"{c}"' for c in ESMR_COLUMNS)
    ids = ", ".join(str(i) for i in facility_ids)
    sql = (
        f'SELECT {cols} FROM "{resource_id}" WHERE "facility_place_id" IN ({ids}) '
        f"AND \"location_place_type\" ILIKE '%Receiving%' LIMIT 30000"
    )
    recs = _ckan("datastore_search_sql?sql=" + urllib.parse.quote(sql))["result"]["records"]
    return pd.DataFrame(recs)


def esmr_to_unified(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)
    df = raw.copy()
    df["facility_place_id"] = pd.to_numeric(df["facility_place_id"], errors="coerce").astype("Int64")
    df = df[df["facility_place_id"].isin(list(ESMR_FACILITIES))]
    meta = df["facility_place_id"].map(lambda i: ESMR_FACILITIES[int(i)])
    out = pd.DataFrame({
        "Source": meta.map(lambda m: m["source"]),
        "Agency": meta.map(lambda m: m["agency"]),
        "StationCode": df["location"],
        "StationName": df["facility_name"].str.strip() + " " + df["location"] + " (" + df["location"].map(
            lambda l: "upstream" if l == "RSW-001" else ("downstream" if l == "RSW-002" else "receiving water")) + ")",
        "StationNote": df["location"].map(ESMR_STATION_NOTES).fillna(df["location_desc"]),
        "Creek": meta.map(lambda m: m["creek"]),
        "Watershed": meta.map(lambda m: m["watershed"]),
        "SampleDate": pd.to_datetime(df["sampling_date"], errors="coerce"),
        "SampleTime": df["sampling_time"],
        "Analyte": df["parameter"],
        "Unit": df["units"],
        "Result": pd.to_numeric(df["result"], errors="coerce"),
        "ResultQualifier": df["qualifier"],
        "DataQuality": "Not rated (permit self-monitoring)",
        "Latitude": meta.map(lambda m: m["lat"]),
        "Longitude": meta.map(lambda m: m["lon"]),
        "LocationApproximate": True,
    })
    params = []
    for a, u in zip(out["Analyte"], out["Unit"]):
        hit = ESMR_PARAMETERS.get(a)
        params.append(hit[0] if hit and u in hit[1] else None)
    out["Parameter"] = params
    # temperature: convert °F to °C, then drop the °F copies (2010-2019 reports listed both)
    is_f = (out["Parameter"] == "Water Temp") & (out["Unit"] == "Degrees F")
    out.loc[is_f, "Result"] = (out.loc[is_f, "Result"] - 32) * 5 / 9
    out.loc[is_f, "Unit"] = "Degrees C"
    out["_was_f"] = is_f
    out = out.sort_values("_was_f").drop_duplicates(
        subset=["Source", "StationCode", "SampleDate", "SampleTime", "Analyte", "Unit"], keep="first"
    ).drop(columns="_was_f")
    return out[UNIFIED_COLUMNS].sort_values(["Source", "StationCode", "SampleDate"]).reset_index(drop=True)


def harvest_esmr(tables: list[dict] | None = None, facility_ids: list[int] | None = None,
                 progress=None, workers: int = 3) -> tuple[pd.DataFrame, list[dict]]:
    tables = tables if tables is not None else esmr_year_tables()
    facility_ids = facility_ids or list(ESMR_FACILITIES)
    frames, problems, done = [], [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_esmr_table, t["id"], facility_ids): t for t in tables}
        for fut in as_completed(futs):
            t = futs[fut]
            done += 1
            try:
                part = fut.result()
                if not part.empty:
                    frames.append(part)
            except Exception as exc:
                problems.append({"table": t["name"], "error": str(exc)})
            if progress:
                progress(done, len(tables), t)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return esmr_to_unified(raw), problems


# ---------------------------------------------------------------------------- USGS download
def fetch_usgs_flow() -> pd.DataFrame:
    sites = ",".join(USGS_FLOW_SITES)
    url = (f"https://waterservices.usgs.gov/nwis/dv/?format=json&sites={sites}"
           f"&parameterCd=00060&startDT=1950-01-01&endDT={date.today():%Y-%m-%d}")
    js = json.loads(_get(url).decode("utf-8"))
    rows = []
    for ts in js.get("value", {}).get("timeSeries", []):
        info = ts["sourceInfo"]
        site = info["siteCode"][0]["value"]
        geo = info["geoLocation"]["geogLocation"]
        name, creek = USGS_FLOW_SITES.get(site, (info["siteName"], "Dry Creek"))
        for block in ts.get("values", []):
            for v in block.get("value", []):
                quals = v.get("qualifiers", [])
                dq = "USGS approved" if "A" in quals else ("USGS provisional" if "P" in quals else "USGS (" + ",".join(quals) + ")")
                rows.append({
                    "Source": SOURCE_USGS, "Agency": "U.S. Geological Survey", "StationCode": f"USGS {site}",
                    "StationName": name, "StationNote": "Stream gauge (daily mean flow)", "Creek": creek,
                    "Watershed": "Dry Creek", "SampleDate": v["dateTime"][:10], "SampleTime": "",
                    "Parameter": None, "Analyte": "Stream flow (daily mean)", "Unit": "cfs",
                    "Result": v["value"], "ResultQualifier": "e" if "e" in quals else "=", "DataQuality": dq,
                    "Latitude": geo["latitude"], "Longitude": geo["longitude"], "LocationApproximate": False,
                })
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


def fetch_usgs_water_quality() -> pd.DataFrame:
    """Field water quality at USGS sites in the watershed box, via the Water Quality Portal."""
    bbox = ",".join(str(x) for x in BBOX)
    chars = "&".join("characteristicName=" + urllib.parse.quote(c) for c in USGS_WQ_CHARACTERISTICS)
    st_url = f"https://www.waterqualitydata.us/data/Station/search?bBox={bbox}&organization=USGS-CA&siteType=Stream&mimeType=csv"
    stations = pd.read_csv(io.BytesIO(_get(st_url)), dtype=str)
    if stations.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)
    name_col = stations["MonitoringLocationName"].str.upper()
    stations["Creek"] = None
    for key, creek in USGS_WQ_NAME_TO_CREEK.items():
        stations.loc[stations["Creek"].isna() & name_col.str.contains(key, regex=False), "Creek"] = creek
    stations = stations[stations["Creek"].notna()]
    if stations.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)
    ids = "&".join("siteid=" + urllib.parse.quote(s) for s in stations["MonitoringLocationIdentifier"])
    res_url = f"https://www.waterqualitydata.us/data/Result/search?{ids}&{chars}&mimeType=csv&dataProfile=resultPhysChem"
    res = pd.read_csv(io.BytesIO(_get(res_url)), dtype=str)
    if res.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)
    st = stations.set_index("MonitoringLocationIdentifier")
    sid = res["MonitoringLocationIdentifier"]
    out = pd.DataFrame({
        "Source": SOURCE_USGS, "Agency": "U.S. Geological Survey",
        "StationCode": sid, "StationName": sid.map(st["MonitoringLocationName"]).str.title(),
        "StationNote": "USGS field water quality sample", "Creek": sid.map(st["Creek"]), "Watershed": "Dry Creek",
        "SampleDate": res["ActivityStartDate"], "SampleTime": res.get("ActivityStartTime/Time", ""),
        "Parameter": res["CharacteristicName"].map(USGS_WQ_CHARACTERISTICS), "Analyte": res["CharacteristicName"],
        "Unit": res["ResultMeasure/MeasureUnitCode"], "Result": pd.to_numeric(res["ResultMeasureValue"], errors="coerce"),
        "ResultQualifier": res.get("ResultDetectionConditionText", "").fillna("=") if "ResultDetectionConditionText" in res else "=",
        "DataQuality": "USGS " + res["ResultStatusIdentifier"].fillna("").str.lower(),
        "Latitude": pd.to_numeric(sid.map(st["LatitudeMeasure"]), errors="coerce"),
        "Longitude": pd.to_numeric(sid.map(st["LongitudeMeasure"]), errors="coerce"),
        "LocationApproximate": False,
    })
    is_f = (out["Parameter"] == "Water Temp") & (out["Unit"].str.contains("F", na=False))
    out.loc[is_f, "Result"] = (out.loc[is_f, "Result"] - 32) * 5 / 9
    out.loc[is_f, "Unit"] = "deg C"
    return out[UNIFIED_COLUMNS]


def harvest_usgs() -> tuple[pd.DataFrame, list[dict]]:
    frames, problems = [], []
    for label, fn in [("USGS daily stream flow", fetch_usgs_flow), ("USGS water quality samples (Water Quality Portal)", fetch_usgs_water_quality)]:
        try:
            frames.append(fn())
        except Exception as exc:
            problems.append({"table": label, "error": str(exc)})
    data = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame(columns=UNIFIED_COLUMNS)
    if not data.empty:
        data["SampleDate"] = pd.to_datetime(data["SampleDate"], errors="coerce")
        data["Result"] = pd.to_numeric(data["Result"], errors="coerce")
    return data, problems


# ---------------------------------------------------------------------------- shared helpers
def latest_file(folder: Path, prefix: str) -> Path | None:
    files = sorted(folder.glob(f"{prefix}_*.csv.gz"))
    return files[-1] if files else None


def ceden_to_unified(df: pd.DataFrame) -> pd.DataFrame:
    """Puts a saved CEDEN download (from download_roseville_ceden_history.py) into the shared column layout."""
    if df.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)
    out = pd.DataFrame({
        "Source": SOURCE_CEDEN, "Agency": df["Program"], "StationCode": df["StationCode"],
        "StationName": df["StationName"], "StationNote": df.get("Dataset", "CEDEN").map(lambda d: f"CEDEN {d} dataset"),
        "Creek": df["Creek"], "Watershed": "Dry Creek", "SampleDate": pd.to_datetime(df["SampleDate"], errors="coerce"),
        "SampleTime": df.get("CollectionTime", ""), "Parameter": df["Parameter"], "Analyte": df["Analyte"],
        "Unit": df["Unit"], "Result": pd.to_numeric(df["Result"], errors="coerce"),
        "ResultQualifier": df.get("ResultQualCode", "="), "DataQuality": df["DataQuality"],
        "Latitude": df["Latitude"], "Longitude": df["Longitude"], "LocationApproximate": False,
    })
    return out[UNIFIED_COLUMNS]


def _save(data: pd.DataFrame, folder: Path, prefix: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{prefix}_{date.today():%Y-%m-%d}.csv.gz"
    if out.exists():
        out = folder / f"{prefix}_{date.today():%Y-%m-%d}_{int(time.time())}.csv.gz"
    data.to_csv(out, index=False, compression="gzip")
    return out


def main() -> None:
    which = set(a.lower() for a in sys.argv[1:]) or {"esmr", "usgs"}
    if "esmr" in which:
        print("eSMR: finding yearly tables on data.ca.gov ...")
        tables = esmr_year_tables()
        print(f"  {len(tables)} tables ({tables[0]['year']}-{tables[-1]['year']}). These are large; this takes several minutes.")
        data, problems = harvest_esmr(tables, progress=lambda d, n, t: print(f"  [{d:>2}/{n}] {t['name']}", flush=True))
        for p in problems:
            print(f"  ! {p['table']}: {p['error']}")
        if data.empty:
            print("  No eSMR records downloaded. Nothing saved.")
        else:
            path = _save(data, ESMR_DIR, "roseville_wwtp_esmr")
            f = data[data["Parameter"].notna()]
            print(f"  Saved {len(data):,} eSMR records ({len(f):,} field-parameter readings, "
                  f"{data['SampleDate'].min():%Y-%m-%d} to {data['SampleDate'].max():%Y-%m-%d}) to {path}")
    if "usgs" in which:
        print("USGS: downloading stream flow and water quality samples ...")
        data, problems = harvest_usgs()
        for p in problems:
            print(f"  ! {p['table']}: {p['error']}")
        if data.empty:
            print("  No USGS records downloaded. Nothing saved.")
        else:
            path = _save(data, USGS_DIR, "dry_creek_usgs")
            print(f"  Saved {len(data):,} USGS records from {data['StationCode'].nunique()} sites to {path}")


if __name__ == "__main__":
    main()

