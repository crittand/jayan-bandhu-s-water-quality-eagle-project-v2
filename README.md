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

## 🌲 Community Stewardship: Dry Creek Conservancy (DCC) & CEDEN 2.0 Integration

This dashboard connects Jayan Bandhu's Eagle Scout field monitoring directly to the mission of the **[Dry Creek Conservancy (DCC)](https://drycreekconservancy.org/)**—a Roseville 501(c)(3) watershed stewardship organization founded in 1995 to protect the **101-square-mile Dry Creek Watershed** across Placer and Sacramento counties:

- **Protecting Salmon & Steelhead Habitat**: Upstream **Miners Ravine (`JBDC01`)** and **Secret Ravine** provide vital spawning and rearing habitat for native **Fall-run Chinook Salmon** and threatened **Central Valley Steelhead Trout**.
- **Tracking Urban "First Flush" Runoff**: Downstream **Saugstad Park (`JBDC02`)** captures mainstem Dry Creek water quality below the urban Roseville confluence, tracking how street storm drains affect conductivity and turbidity.
- **Statewide CEDEN 2.0 Export & Multi-Year Historical Harvester**: Automatically converts Eagle Project field data into California's official **17-column CEDEN 2.0 format** and harvests historical Roseville monitoring records (2000–2026) from `data.ca.gov` (including standalone CLI script `download_roseville_ceden_history.py`).

## 🚀 Run Locally in VS Code

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run waterquality.py
```

To harvest all historical Roseville CEDEN records (2000–2026) from the command line:

```bash
python3 download_roseville_ceden_history.py
```
