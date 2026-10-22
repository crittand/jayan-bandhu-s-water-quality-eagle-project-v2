#!/usr/bin/env python3
"""
Pulls CEDEN water quality records for the Dry Creek watershed (Roseville) off data.ca.gov
(State Water Resources Control Board). Searches every year of:
  - Surface Water - Chemistry Results
  - Surface Water - Habitat Results
  - Surface Water - Chemistry Results - CEDEN Augmentation  (newer stuff not loaded into CEDEN yet)

Column names come from the CEDEN data dictionaries on data.ca.gov. NOTE the lat/long
columns are "Latitude" / "Longitude" -- "Target Latitude" is just the label. The old
version used the label and every request failed (and the error got swallowed)

Which stations count:
  inside a box around the watershed (Rio Linda -> Loomis/Granite Bay) AND the station
  name has one of the watershed creeks in it (list from DCC's sub-watershed map).
  Storm drains / outfalls / Steelhead Creek are skipped. The box keeps out the other
  "Dry Creeks" (Sonoma etc), the names keep out Pleasant Grove, Arcade, Auburn Ravine...

run:   python3 download_roseville_ceden_history.py
saves: Raw_data/ceden/dry_creek_watershed_ceden_YYYY-MM-DD.csv.gz  (new file every time, never overwrites)
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd

CKAN_BASE = "https://data.ca.gov/api/3/action"
USER_AGENT = "DryCreekConservancyDashboard/2.0"

DATASETS = {
    "surface-water-chemistry-results": "Chemistry",
    "surface-water-habitat-results": "Habitat",
    "surface-water-chemistry-results-ceden-augmentation": "Chemistry (Augmentation)",
}

# watershed box
LAT_MIN, LAT_MAX = 38.64, 38.90
LON_MIN, LON_MAX = -121.48, -121.08

# creek -> how it shows up in station names
WATERSHED_CREEKS = {
    "Dry Creek": ["Dry Creek", "Dry Cr."],
    "Secret Ravine": ["Secret Ravine"],
    "Miners Ravine": ["Miners Ravine", "Miner's Ravine", "Miners Rv"],
    "Antelope Creek": ["Antelope Creek", "Antelope Cr."],
    "Clover Valley Creek": ["Clover Valley"],
    "Linda Creek": ["Linda Creek", "Linda Cr."],
    "Cirby Creek": ["Cirby"],
    "Strap Ravine": ["Strap Ravine"],
    "Sucker Ravine": ["Sucker Ravine"],
}
EXCLUDE_NAME_PATTERNS = ["Storm Drain", "Outfall", "Steelhead Creek"]

# columns that exist in all 3 datasets (habitat has no ResultsReplicate so its not here)
COLUMNS = [
    "Program", "Project", "SampleAgency", "StationCode", "StationName", "SampleDate",
    "CollectionTime", "MatrixName", "MethodName", "SampleTypeCode", "Analyte", "Unit",
    "Result", "ResultQualCode", "DataQuality", "DataQualityIndicator", "Latitude",
    "Longitude", "Datum", "CollectionReplicate",
]

# DataQuality values. dictionary says "Passed QC"/"Reject Data"/"Metadata, QC record" but the
# actual tables say "Passed"/"Reject record"/"MetaData". so both spellings :/
DQ_NOT_MEASUREMENTS = ["Metadata, QC record", "MetaData"]
DQ_REJECTED = ["Reject Data", "Reject record"]

# our 5 field params -> (CEDEN analyte prefix, units we accept)
PARAMETERS = {
    "DO": ("Oxygen, Dissolved", ["mg/L"]),
    "SPC": ("SpecificConductivity", ["uS/cm", "umhos/cm", "µS/cm"]),
    "PH": ("pH", ["none", "pH units", "pH Units", "pH"]),
    "Turbidity": ("Turbidity", ["NTU"]),
    "Water Temp": ("Temperature", ["Deg C", "Deg F"]),
}
PARAMETER_LABELS = {
    "DO": "Dissolved Oxygen (mg/L)",
    "SPC": "Specific Conductance (µS/cm)",
    "PH": "pH",
    "Turbidity": "Turbidity (NTU)",
    "Water Temp": "Water Temperature (°C)",
}

RAW_DIR = Path(__file__).parent / "Raw_data" / "ceden"
PAGE_SIZE = 30000  # data.ca.gov caps sql results at 32k rows


def _api(path: str, timeout: int = 120, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{CKAN_BASE}/{path}", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in (400, 409):
                try:
                    msg = json.loads(body)["error"]
                except Exception:
                    msg = body[:300]
                last = f"data.ca.gov rejected the query (HTTP {exc.code}): {str(msg)[:300]}"
                # "Query took too long" = server is busy, wait + retry. anything else is a real error
                if "took too long" not in str(msg).lower():
                    raise RuntimeError(last) from None
                time.sleep(10 * (attempt + 1))
                continue
            last = f"HTTP {exc.code}"
        except Exception as exc:  # timeouts etc
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last if last and last.startswith("data.ca.gov") else f"data.ca.gov did not respond ({last})")


def list_year_tables(datasets: list[str] | None = None) -> list[dict]:
    # skip the giant "All Years" bulk files, the yearly ones have the same data
    out = []
    for pkg in datasets or list(DATASETS):
        resources = _api(f"package_show?id={urllib.parse.quote(pkg)}", timeout=30)["result"]["resources"]
        for r in resources:
            if not r.get("datastore_active") or "All Years" in r.get("name", ""):
                continue
            name = r.get("name", r["id"])
            m = re.match(r"\s*(\d{4})", name)
            if m:
                year = m.group(1)
            elif "Prior to 2000" in name:
                year = "Before 2000"
            else:
                year = "2020 onward"  # augmentation is one big table
            out.append({"dataset": pkg, "dataset_label": DATASETS[pkg], "name": name, "id": r["id"], "year": year})
    return out


def _station_filter_sql() -> str:
    names = [p for pats in WATERSHED_CREEKS.values() for p in pats]
    name_or = " OR ".join("\"StationName\" ILIKE '%{}%'".format(n.replace("'", "''")) for n in names)
    excl = " AND ".join("\"StationName\" NOT ILIKE '%{}%'".format(n) for n in EXCLUDE_NAME_PATTERNS)
    return (
        f'"Latitude" BETWEEN {LAT_MIN} AND {LAT_MAX} AND "Longitude" BETWEEN {LON_MIN} AND {LON_MAX} '
        f"AND ({name_or}) AND {excl}"
    )


def fetch_table(resource_id: str) -> pd.DataFrame:
    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    base = f'SELECT {cols} FROM "{resource_id}" WHERE {_station_filter_sql()}'
    # one plain query is almost always enough (ORDER BY made the 2024 table time out)
    records = _api("datastore_search_sql?sql=" + urllib.parse.quote(f"{base} LIMIT {PAGE_SIZE}"))["result"]["records"]
    if len(records) < PAGE_SIZE:
        return pd.DataFrame(records) if records else pd.DataFrame(columns=COLUMNS)
    # more than 1 page -> page through it sorted
    frames, offset = [], 0
    while True:
        sql = f'{base} ORDER BY "_id" LIMIT {PAGE_SIZE} OFFSET {offset}'
        records = _api("datastore_search_sql?sql=" + urllib.parse.quote(sql))["result"]["records"]
        if records:
            frames.append(pd.DataFrame(records))
        if len(records) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return pd.concat(frames, ignore_index=True)


def creek_for_station(station_name: str) -> str:
    # whichever creek name shows up FIRST in the station name ("Cirby Creek above Linda Cr." -> Cirby)
    s = str(station_name).lower()
    best, pos = "Other (Dry Creek Watershed)", len(s) + 1
    for creek, pats in WATERSHED_CREEKS.items():
        for p in pats:
            i = s.find(p.lower())
            if 0 <= i < pos:
                best, pos = creek, i
    return best


def parameter_for(analyte: str, unit: str, matrix: str = "samplewater") -> str | None:
    # only creek water (samplewater) - there are air temps and lab blanks in there too
    if str(matrix).lower() != "samplewater":
        return None
    a, u = str(analyte), str(unit)
    for code, (prefix, units) in PARAMETERS.items():
        if a.lower().startswith(prefix.lower()) and u in units:
            if code == "Water Temp" and not a.lower().startswith("temperature"):
                return None
            return code
    return None


def clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["Result"] = pd.to_numeric(df["Result"], errors="coerce")
    df.loc[df["Result"] == -88, "Result"] = pd.NA  # -88 means not recorded
    df["SampleDate"] = pd.to_datetime(df["SampleDate"], errors="coerce", format="mixed").dt.tz_localize(None)
    df.loc[df["SampleDate"] == pd.Timestamp("1950-01-01"), "SampleDate"] = pd.NaT  # 1/1/1950 = unknown date
    df["Creek"] = df["StationName"].apply(creek_for_station)
    df["Parameter"] = [parameter_for(a, u, m) for a, u, m in zip(df["Analyte"], df["Unit"], df["MatrixName"])]
    # F -> C
    is_f = (df["Parameter"] == "Water Temp") & (df["Unit"] == "Deg F")
    df.loc[is_f, "Result"] = (df.loc[is_f, "Result"] - 32) * 5 / 9
    df.loc[is_f, "Unit"] = "Deg C"
    return df


def harvest(tables: list[dict], progress=None, workers: int = 3) -> tuple[pd.DataFrame, list[dict]]:
    # returns (data, problems). problems get passed back so the app can SHOW them (old code hid them)
    frames, problems = [], []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_table, t["id"]): t for t in tables}
        for fut in as_completed(futures):
            t = futures[fut]
            done += 1
            try:
                part = fut.result()
                if not part.empty:
                    part["Dataset"] = t["dataset_label"]
                    part["SourceTable"] = t["name"]
                    frames.append(part)
            except Exception as exc:
                problems.append({"table": t["name"], "error": str(exc)})
            if progress:
                progress(done, len(tables), t)
    data = clean(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame()
    return data, problems


def latest_saved_extract(raw_dir: Path = RAW_DIR) -> Path | None:
    files = sorted(list(raw_dir.glob("dry_creek_watershed_ceden_*.csv.gz")) + list(raw_dir.glob("dry_creek_watershed_ceden_*.csv")))
    return files[-1] if files else None


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Finding CEDEN tables on data.ca.gov ...")
    tables = list_year_tables()
    print(f"  {len(tables)} tables across {len(DATASETS)} datasets")

    def show(done, total, t):
        print(f"  [{done:>2}/{total}] {t['dataset_label']:<25} {t['name']}")

    data, problems = harvest(tables, progress=show)
    if problems:
        print(f"\n{len(problems)} table(s) could not be downloaded:")
        for p in problems:
            print(f"  - {p['table']}: {p['error']}")
    if data.empty:
        print("\nNo records downloaded. Nothing saved.")
        return

    # gzip so the repo doesnt get huge, pandas reads .csv.gz fine
    out_csv = RAW_DIR / f"dry_creek_watershed_ceden_{date.today():%Y-%m-%d}.csv.gz"
    if out_csv.exists():  # ran twice in one day, keep both
        out_csv = RAW_DIR / f"dry_creek_watershed_ceden_{date.today():%Y-%m-%d}_{int(time.time())}.csv.gz"
    data.to_csv(out_csv, index=False, compression="gzip")
    field = data[data["Parameter"].notna()]
    print(
        f"\nSaved {len(data):,} records from {data['StationCode'].nunique()} stations "
        f"({data['SampleDate'].min():%Y}–{data['SampleDate'].max():%Y}) to {out_csv}"
    )
    print(f"  Field parameters (DO, SPC, pH, turbidity, water temp): {len(field):,} records")
    if problems:
        print("  NOTE: some tables failed (listed above). Re-run later to fill them in.")


if __name__ == "__main__":
    main()
