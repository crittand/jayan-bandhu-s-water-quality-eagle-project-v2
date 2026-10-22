#!/usr/bin/env python3
"""
Standalone Historical CEDEN 2.0 Downloader for Roseville, CA Monitoring Stations
================================================================================
Crawls the California Open Data Portal (https://data.ca.gov) CKAN API across ALL
historical annual Surface Water Chemistry & Habitat/Field datasets (2000-present)
to download every historical water quality record in the Roseville / Dry Creek
Watershed (Dry Creek, Secret Ravine, Miner's Ravine, Antelope Creek, Linda Creek,
Strap Ravine).

Uses a dual filter:
1. Geospatial Bounding Box around Roseville & the Dry Creek Watershed
   (Latitude 38.70 to 38.85 N, Longitude -121.40 to -121.15 W) so we capture all
   stations inside Roseville while excluding unrelated 'Dry Creek' streams in
   Sonoma or Fresno counties.
2. Waterway / Station Name match ('Roseville', 'Dry Creek', 'Secret Ravine',
   'Miners Ravine', 'Antelope Creek', 'Linda Creek', 'Strap Ravine', '519%').

Usage in VS Code Terminal:
    python3 download_roseville_ceden_history.py
"""

from __future__ import annotations

import json
from pathlib import Path
import urllib.parse
import urllib.request
import pandas as pd

CKAN_BASE = "https://data.ca.gov/api/3/action"
PACKAGES = [
    "surface-water-chemistry-results",
    "surface-water-habitat-results",
]

# Roseville / Dry Creek Watershed Bounding Box (Placer & N. Sacramento County)
LAT_MIN, LAT_MAX = 38.70, 38.85
LON_MIN, LON_MAX = -121.40, -121.15


def discover_historical_resources(package_id: str) -> list[dict]:
    """Queries data.ca.gov package_show to discover all yearly DataStore tables."""
    url = f"{CKAN_BASE}/package_show?id={urllib.parse.quote(package_id)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RosevilleCreeksEagleProject/2.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    resources = payload.get("result", {}).get("resources", [])
    active = []
    for r in resources:
        if r.get("datastore_active"):
            active.append(
                {
                    "package": package_id,
                    "name": r.get("name", "Unnamed Resource"),
                    "id": r.get("id"),
                    "created": r.get("created", ""),
                }
            )
    return active


def query_roseville_resource(resource_id: str, resource_name: str, limit: int = 5000) -> pd.DataFrame:
    """Queries a single annual CEDEN resource table for Roseville / Dry Creek stations."""
    sql = (
        f'SELECT * FROM "{resource_id}" '
        f"WHERE ("
        f"  (CAST(\"TargetLatitude\" AS FLOAT) BETWEEN {LAT_MIN} AND {LAT_MAX} "
        f"   AND CAST(\"TargetLongitude\" AS FLOAT) BETWEEN {LON_MIN} AND {LON_MAX}) "
        f"  OR (\"StationName\" ILIKE '%Roseville%') "
        f"  OR (\"StationName\" ILIKE '%Secret Ravine%') "
        f"  OR (\"StationName\" ILIKE '%Miners Ravine%' OR \"StationName\" ILIKE '%Miner''s Ravine%') "
        f"  OR (\"StationName\" ILIKE '%Antelope Creek%' AND \"TargetLatitude\" > 38.6) "
        f"  OR (\"StationName\" ILIKE '%Linda Creek%' AND \"TargetLatitude\" > 38.6) "
        f"  OR (\"StationName\" ILIKE '%Dry Creek%' AND \"TargetLatitude\" BETWEEN {LAT_MIN} AND {LAT_MAX})"
        f") LIMIT {limit}"
    )
    url = f"{CKAN_BASE}/datastore_search_sql?sql={urllib.parse.quote(sql)}"
    req = urllib.request.Request(url, headers={"User-Agent": "RosevilleCreeksEagleProject/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    records = payload.get("result", {}).get("records", [])
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["SourceResource"] = resource_name
    return df


def main() -> None:
    out_dir = Path(__file__).parent / "Raw_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "roseville_ceden_samples.csv"

    all_frames = []
    for pkg in PACKAGES:
        print(f"Discovering historical CEDEN tables in '{pkg}'...")
        try:
            resources = discover_historical_resources(pkg)
            print(f"  Found {len(resources)} active annual/historical tables.")
        except Exception as exc:
            print(f"  Could not query package '{pkg}': {exc}")
            continue

        for res in resources:
            r_name = res["name"]
            r_id = res["id"]
            print(f"  -> Querying {r_name} ({r_id})...", end=" ", flush=True)
            try:
                df_part = query_roseville_resource(r_id, r_name)
                print(f"{len(df_part)} Roseville rows found.")
                if not df_part.empty:
                    all_frames.append(df_part)
            except Exception as exc:
                print(f"skipped ({exc})")

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined.to_csv(out_csv, index=False)
        print(f"\nSaved {len(combined):,} historical Roseville CEDEN records to {out_csv}!")
    else:
        print("\nNo live records fetched (check internet connection).")


if __name__ == "__main__":
    main()
