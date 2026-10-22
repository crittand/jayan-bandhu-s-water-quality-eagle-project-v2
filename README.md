# Jayan-Bandhu's-Water-Quality-Eagle-Project
This is an Eagle project that aims to track the creek health of the Dry Creek Watershed using eDNA and water chemistry measurements. Physiochemical measurements will be conducted on a monthly basis.

This Eagle project contains two main components: **eDNA** and **physiochemical** monitoring.

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
