"""
saving monitoring data that partners upload, so it actually sticks around.

streamlit cloud throws away any files the app writes whenever it restarts, so when
there's a github token in st.secrets every upload ALSO gets committed to the repo
(streamlit cloud then redeploys with the new files). no token = local files only,
which is fine on a laptop but NOT permanent on streamlit cloud.

files:
  Raw_data/community/sites.csv                       every registered site (JBDC01/02 are in there too)
  Raw_data/community/samples/<org>_<timestamp>.csv   one file per upload, so two uploads at the
                                                     same time can't overwrite each other
the original field data in Raw_data/original/ is never touched.
"""

import base64
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
COMMUNITY_DIR = BASE_DIR / "Raw_data" / "community"
SITES_FILE = COMMUNITY_DIR / "sites.csv"
SAMPLES_DIR = COMMUNITY_DIR / "samples"

SITE_COLUMNS = ["SiteCode", "SiteName", "Organization", "Creek", "Watershed", "Latitude", "Longitude", "AddedOn", "Notes"]
PARAMS = ["DO", "SPC", "PH", "Turbidity", "Water Temp"]
EXTRA_COLS = ["Water Level", "Precip", "Air Temp(C)", "DO(pct)"]   # same optional columns as our field sheet
SAMPLE_COLUMNS = ["Date", "Site"] + PARAMS + EXTRA_COLS + ["Organization", "UploadBatch", "UploadedOn"]

# outside these = physically impossible / wrong units -> value gets rejected
HARD_LIMITS = {"DO": (0, 25), "SPC": (0, 10000), "PH": (0, 14), "Turbidity": (0, 5000), "Water Temp": (-5, 45)}
# outside these = unusual, still saved but we warn (same ranges the old sidebar uploader used)
WARN_RANGES = {"DO": (4, 20), "SPC": (10, 1000), "PH": (4, 11), "Turbidity": (0, 500), "Water Temp": (0, 40)}

# header names people actually use -> our names. compared after lowercasing + dropping units in ()
ALIASES = {
    "Date": ["date", "sample date", "sampledate", "sampling date", "collection date", "datetime", "date sampled"],
    "Site": ["site", "site code", "sitecode", "site id", "station", "station code", "stationcode", "station id", "location"],
    "DO": ["do", "dissolved oxygen", "do mg/l", "oxygen", "dissolved o2", "do conc"],
    "SPC": ["spc", "specific conductance", "spec cond", "spcond", "conductivity", "cond", "ec", "sp cond", "specific conductivity"],
    "PH": ["ph"],
    "Turbidity": ["turbidity", "turb", "ntu"],
    "Water Temp": ["water temp", "water temperature", "temp", "temperature", "wtemp", "water temp c", "h2o temp"],
}

SITE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,19}$")


# ----------------------------------------------------------------- reading
def default_sites():
    return pd.DataFrame([
        {"SiteCode": "JBDC01", "SiteName": "Miners Ravine", "Organization": "Dry Creek Conservancy", "Creek": "Miners Ravine",
         "Watershed": "Dry Creek", "Latitude": 38.752945, "Longitude": -121.241526, "AddedOn": "2025-10-12", "Notes": "original monitoring site"},
        {"SiteCode": "JBDC02", "SiteName": "Saugstad Park (Dry Creek)", "Organization": "Dry Creek Conservancy", "Creek": "Dry Creek",
         "Watershed": "Dry Creek", "Latitude": 38.742738, "Longitude": -121.284156, "AddedOn": "2025-10-12", "Notes": "original monitoring site"},
    ], columns=SITE_COLUMNS)


def load_sites():
    if SITES_FILE.exists():
        s = pd.read_csv(SITES_FILE, dtype={"SiteCode": str})
        for c in SITE_COLUMNS:
            if c not in s.columns:
                s[c] = None
        return s[SITE_COLUMNS]
    return default_sites()


def load_samples():
    files = sorted(SAMPLES_DIR.glob("*.csv")) if SAMPLES_DIR.exists() else []
    frames = [pd.read_csv(f, dtype={"Site": str}) for f in files]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=SAMPLE_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    for c in SAMPLE_COLUMNS:
        if c not in out.columns:
            out[c] = None
    return out[SAMPLE_COLUMNS]


def data_version():
    # changes whenever a file is added/updated -> used as a cache key in the app
    files = [SITES_FILE] + (sorted(SAMPLES_DIR.glob("*.csv")) if SAMPLES_DIR.exists() else [])
    return tuple((f.name, f.stat().st_mtime) for f in files if f.exists())


# ----------------------------------------------------------------- checking an upload
def _norm(h):
    h = re.sub(r"\(.*?\)", "", str(h)).lower()
    h = re.sub(r"[^a-z0-9/ ]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def guess_columns(columns):
    """best guess of which file column is which field. {field: column or None}"""
    normed = {c: _norm(c) for c in columns}
    out = {}
    for field, names in ALIASES.items():
        hit = next((c for c, n in normed.items() if n in names), None)
        if hit is None:  # looser: header starts with an alias, e.g. "Temp C" or "DO mg/L"
            hit = next((c for c, n in normed.items() if any(n.startswith(a + " ") for a in names if len(a) > 1)), None)
        out[field] = hit
    # dont let one column get used twice (e.g. "Temp" matching both temps)
    used = set()
    for f in out:
        if out[f] in used:
            out[f] = None
        elif out[f]:
            used.add(out[f])
    return out


def clean_upload(raw, mapping, temp_in_f=False):
    """
    raw = whatever they uploaded, mapping = {field: column}. returns (clean, problems, warnings)
    problems are things that got dropped / rejected, warnings are just heads-ups.
    """
    problems, warnings = [], []
    df = pd.DataFrame(index=raw.index)
    for field in ["Date", "Site"] + PARAMS:
        col = mapping.get(field)
        df[field] = raw[col] if col else None
    for c in EXTRA_COLS:
        df[c] = raw[c] if c in raw.columns else None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", format="mixed")
    df["Site"] = df["Site"].astype(str).str.strip().str.upper().replace({"NAN": None, "": None, "NONE": None})
    bad = df["Date"].isna() | df["Site"].isna()
    if bad.any():
        problems.append(f"{int(bad.sum())} row(s) skipped: missing or unreadable date / site.")
    df = df[~bad]

    for p in PARAMS:
        df[p] = pd.to_numeric(df[p], errors="coerce")
    if temp_in_f:
        df["Water Temp"] = (df["Water Temp"] - 32) * 5 / 9

    for p in PARAMS:
        lo, hi = HARD_LIMITS[p]
        imp = df[p].notna() & ((df[p] < lo) | (df[p] > hi))
        if imp.any():
            msg = f"{p}: {int(imp.sum())} impossible value(s) removed (allowed {lo}–{hi}). Check units?"
            if p == "Water Temp" and not temp_in_f and df.loc[imp, p].between(32, 110).all():
                msg = f"Water Temp: {int(imp.sum())} value(s) look like °F, not °C. Turn on the °F switch above and they'll be converted."
            problems.append(msg)
            df.loc[imp, p] = None
        wlo, whi = WARN_RANGES[p]
        odd = df[p].notna() & ((df[p] < wlo) | (df[p] > whi))
        if odd.any():
            warnings.append(f"{p}: {int(odd.sum())} unusual value(s) outside {wlo}–{whi}. Saved anyway, double check them.")

    none = df[PARAMS].isna().all(axis=1)
    if none.any():
        problems.append(f"{int(none.sum())} row(s) skipped: no DO / SPC / pH / turbidity / water temp values.")
    df = df[~none]

    dup = df.duplicated(subset=["Site", "Date"], keep="first")
    if dup.any():
        problems.append(f"{int(dup.sum())} duplicate row(s) in the file (same site + date) skipped.")
    df = df[~dup]
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    return df.reset_index(drop=True), problems, warnings


def drop_existing(clean, existing):
    """rows for a site + date we already have are skipped (corrections aren't supported yet)"""
    if clean.empty or existing.empty:
        return clean, 0
    have = set(zip(existing["Site"].astype(str).str.upper(), pd.to_datetime(existing["Date"], format="mixed").dt.strftime("%Y-%m-%d")))
    keep = [(s, d) not in have for s, d in zip(clean["Site"], clean["Date"])]
    return clean[keep].reset_index(drop=True), int(len(clean) - sum(keep))


def check_new_sites(new_sites, existing_sites):
    errs = []
    taken = set(existing_sites["SiteCode"].astype(str).str.upper())
    for _, r in new_sites.iterrows():
        code = str(r["SiteCode"]).upper()
        if not SITE_CODE_RE.match(code):
            errs.append(f"{code}: site code should be 3-20 letters/numbers (dashes/underscores ok), like ARDC01.")
        if code in taken:
            errs.append(f"{code}: that site code is already used.")
        if not str(r.get("SiteName") or "").strip():
            errs.append(f"{code}: needs a site name.")
        lat, lon = pd.to_numeric(r.get("Latitude"), errors="coerce"), pd.to_numeric(r.get("Longitude"), errors="coerce")
        if pd.isna(lat) or pd.isna(lon):
            errs.append(f"{code}: needs latitude + longitude (decimal degrees) so it can go on the map.")
        elif not (32 <= lat <= 42.1 and -124.5 <= lon <= -114):
            errs.append(f"{code}: {lat}, {lon} isn't in California. Longitude should be negative, e.g. -121.24.")
    return errs


# ----------------------------------------------------------------- saving
def _gh(cfg, method, repo_path, body=None):
    url = f"https://api.github.com/repos/{cfg['repo']}/contents/{urllib.parse.quote(repo_path)}"
    if method == "GET":
        url += f"?ref={urllib.parse.quote(cfg.get('branch', 'main'))}"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "DryCreekConservancyDashboard",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def github_put(cfg, repo_path, content, message):
    """create or update one file in the repo. returns the commit url"""
    for attempt in range(3):
        sha = None
        try:
            sha = _gh(cfg, "GET", repo_path)["sha"]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        body = {"message": message, "content": base64.b64encode(content).decode(), "branch": cfg.get("branch", "main")}
        # sign the commit as a generic bot, otherwise github puts the token owner's name + email on it (public repo!)
        bot = {"name": cfg.get("bot_name", "DCC Dashboard Uploads"), "email": cfg.get("bot_email", "dashboard-uploads@noreply.invalid")}
        body["author"] = body["committer"] = bot
        if sha:
            body["sha"] = sha
        try:
            return _gh(cfg, "PUT", repo_path, body)["commit"]["html_url"]
        except urllib.error.HTTPError as e:
            if e.code in (409, 422) and attempt < 2:   # someone else changed the file in between, try again
                time.sleep(1.5)
                continue
            raise


def _slug(org):
    return re.sub(r"[^a-z0-9]+", "-", org.lower()).strip("-")[:40] or "org"


def save_upload(samples, new_sites, org, github_cfg=None):
    """
    writes the new sites + one samples file locally, then commits them to github if github_cfg is set.
    returns {"saved_to": "github"|"local", "files": [...], "commits": [...], "error": str|None}
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch = f"{_slug(org)}_{stamp}"
    out = {"saved_to": "local", "files": [], "commits": [], "error": None, "batch": batch}

    COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    sites_bytes = None
    if new_sites is not None and not new_sites.empty:
        ns = new_sites.copy()
        ns["SiteCode"] = ns["SiteCode"].astype(str).str.upper()
        ns["Organization"] = org
        ns["AddedOn"] = datetime.now().strftime("%Y-%m-%d")
        for c in SITE_COLUMNS:
            if c not in ns.columns:
                ns[c] = None
        all_sites = pd.concat([load_sites(), ns[SITE_COLUMNS]], ignore_index=True)
        sites_bytes = all_sites.to_csv(index=False).encode()
        SITES_FILE.write_bytes(sites_bytes)
        out["files"].append(str(SITES_FILE.relative_to(BASE_DIR)))

    s = samples.copy()
    s["Organization"] = org
    s["UploadBatch"] = batch
    s["UploadedOn"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    for c in SAMPLE_COLUMNS:
        if c not in s.columns:
            s[c] = None
    sample_path = SAMPLES_DIR / f"{batch}.csv"
    sample_bytes = s[SAMPLE_COLUMNS].to_csv(index=False).encode()
    sample_path.write_bytes(sample_bytes)
    out["files"].append(str(sample_path.relative_to(BASE_DIR)))

    if github_cfg and github_cfg.get("token") and github_cfg.get("repo"):
        try:
            if sites_bytes is not None:
                # re-read sites.csv from github first in case another upload added a site since this app started
                try:
                    remote = _gh(github_cfg, "GET", "Raw_data/community/sites.csv")
                    remote_sites = pd.read_csv(io.BytesIO(base64.b64decode(remote["content"])), dtype={"SiteCode": str})
                    merged = pd.concat([remote_sites, ns[SITE_COLUMNS]], ignore_index=True).drop_duplicates("SiteCode", keep="first")
                    sites_bytes = merged[SITE_COLUMNS].to_csv(index=False).encode()
                except urllib.error.HTTPError:
                    pass
                out["commits"].append(github_put(github_cfg, "Raw_data/community/sites.csv", sites_bytes,
                                                 f"New monitoring site(s) from {org}: {', '.join(ns['SiteCode'])}"))
            out["commits"].append(github_put(github_cfg, f"Raw_data/community/samples/{batch}.csv", sample_bytes,
                                             f"Monitoring data upload from {org} ({len(s)} rows)"))
            out["saved_to"] = "github"
        except Exception as e:
            out["error"] = f"Saved on this server, but saving to GitHub failed: {e}"
    return out
