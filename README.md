# DCC-Water-Quality-Project
This project that aims to track the creek health of the Dry Creek Watershed using eDNA and water chemistry measurements. Physiochemical measurements will be conducted on a monthly basis.

This project contains two main components: **eDNA** and **physiochemical** monitoring.

### 🧬 eDNA Types & Laboratory Partners
1. **Monthly Metabarcoding of BMI (Benthic Macroinvertebrates)**: Conducted to understand how the presence of pollution-sensitive organisms is affected by characteristics of the two creeks (`JBDC01` Miners Ravine and `JBDC02` Dry Creek at Saugstad Park). Samples are collected as part of a Boy Scout Eagle project, processed by the **CALeDNA lab at UC Santa Cruz (UCSC)**, and shared publicly on **eDNA Explorer**.
2. **Quantitative qPCR Assays (Invasive Species Modeling)**: Measured quantitatively to model the spread of two potent invasive species: **New Zealand Mudsnails** (*Potamopyrgus antipodarum*) and **Asian Clams** (*Corbicula fluminea*). All qPCR assays are analyzed by the **Jonah Ventures laboratory**.

### 🧪 Monthly Physiochemical Monitoring & Equipment Partner
Physiochemical monitoring is conducted monthly across `JBDC01` (Miners Ravine) and `JBDC02` (Dry Creek at Saugstad Park). The 5 target parameters are:
- **Conductivity (`SPC`)**
- **pH (`PH`)**
- **Dissolved Oxygen (`DO`)**
- **Water Temperature (`Water Temp`)**
- **Turbidity (`Turbidity`)**

All field monitoring equipment is loaned from the **Sierra Streams Institute**.

---

## 🌲 Community Stewardship: Dry Creek Conservancy (DCC) & CEDEN Integration

This dashboard connects Jayan Bandhu's Eagle Scout field monitoring directly to the mission of the **[Dry Creek Conservancy (DCC)](https://drycreekconservancy.org/)**—a Roseville 501(c)(3) watershed stewardship organization founded in 1995 to protect the **101-square-mile Dry Creek Watershed** across Placer and Sacramento counties:

- **Protecting Salmon & Steelhead Habitat**: Upstream **Miners Ravine (`JBDC01`)** and **Secret Ravine** provide vital spawning and rearing habitat for native **Fall-run Chinook Salmon** and threatened **Central Valley Steelhead Trout**.
- **Tracking Urban "First Flush" Runoff**: Downstream **Saugstad Park (`JBDC02`)** captures mainstem Dry Creek water quality below the urban Roseville confluence, tracking how street storm drains affect conductivity and turbidity.
- **CEDEN Export & Historical Data**: Exports field data as CEDEN-style rows (column names, analyte names, and defaults from the State Water Board's CEDEN data dictionary; a starting point for a CEDEN submission, not the official template). The **Historical Analysis** tab shows real CEDEN records for the Dry Creek Watershed (2000–2023, 57 stations) downloaded from `data.ca.gov` by `download_roseville_ceden_history.py`.

## 🚀 Run Locally in VS Code

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run waterquality.py
```

To download the latest CEDEN records for the Dry Creek Watershed from the command line:

```bash
python3 download_roseville_ceden_history.py
```

This searches the CEDEN Chemistry, Habitat, and Augmentation datasets on data.ca.gov (every year) and saves a new dated file, `Raw_data/ceden/dry_creek_watershed_ceden_YYYY-MM-DD.csv.gz`. It never overwrites an earlier download. The dashboard uses the newest file in that folder.

To download the other historical sources (City of Roseville wastewater plants' creek monitoring from eSMR, and USGS stream flow / samples):

```bash
python3 download_esmr_usgs_history.py          # both (eSMR takes ~5-10 minutes)
python3 download_esmr_usgs_history.py usgs     # just USGS
```

These save to `Raw_data/esmr/` and `Raw_data/usgs/`. The **Historical Analysis** tab lets you pick any combination of CEDEN, eSMR (Dry Creek WWTP, Pleasant Grove WWTP), and USGS. DCC's own JBDC01/JBDC02 sampling stays on the monitoring tabs.

## 🧩 How the code is organized

```
waterquality.py              entry point, just wires things together
dcc_dashboard/
  data.py                    loads the field/lab data + partner uploads -> `ctx`
  shared.py                  thresholds, charts, PDF + CEDEN export helpers
  banner.py                  salmon event QR box
  sidebar.py                 tab picker + quick guide
  tabs/
    __init__.py              list of every tab (key -> label -> file)
    overview.py, dcc_mission.py, creek_detail.py (Dry creek + Miners Ravine), monitoring_sites.py,
    comparative.py, correlation.py, downloads.py, edna.py, simulation.py, upload.py, historical.py
site_data_store.py           partner upload checks + saving (GitHub)
download_*.py                historical data downloaders (also run from the command line)
```

**Adding a new tab:** make `dcc_dashboard/tabs/my_tab.py` with a `def render(ctx):` function and add a line to `TABS` in `tabs/__init__.py` (that list is also the sidebar order). `ctx` has `data`, `miners_ravine`, `dry_creek`, `all_samples`, `sites_df`, `qpcr`.

The salmon event details (name, date, link) are at the top of `dcc_dashboard/banner.py`.

## 📍 Adding partner data (new sites or more samples)

The **📤 Upload Data** tab has two modes:

- **🔍 Explore a file (not saved)**: anyone can chart a CSV. Nothing is stored.
- **📥 Add data to the dashboard (partners)**: an organization signs in with its passcode and uploads a CSV for **new sites** or **more samples on its own sites**. It's saved and shows up on the **📍 Monitoring Sites** tab right away. New JBDC01 / JBDC02 samples also show up on the Dry creek / Miners Ravine tabs.

How it's checked: column names are matched automatically (and can be fixed by hand), °F temperatures can be converted, impossible values (wrong units) are removed, rows for a site + date that already exist are skipped, and organizations can only add to their own sites. New sites need a name and latitude/longitude.

Where it's stored:

- `Raw_data/community/sites.csv`: every registered site
- `Raw_data/community/samples/<organization>_<timestamp>.csv`: one file per upload
- The original field data in `Raw_data/original/` is never changed.

### Setup (once)

1. Copy `.streamlit/secrets.toml.example` and fill in a passcode for each organization.
   - Local: save it as `.streamlit/secrets.toml` (it's git-ignored).
   - Streamlit Cloud: app ⋮ menu → **Settings → Secrets**, paste it in.
2. **For uploads to be permanent on Streamlit Cloud**, add the `[github]` section with a GitHub *fine-grained personal access token* limited to this repo with **Contents: Read and write**. Each upload is then committed to the repo, and Streamlit Cloud redeploys with it (the app restarts for a few seconds). Without the token, uploads only last until the app restarts.
3. Give each organization its passcode. To remove an organization, delete its line from the secrets.
