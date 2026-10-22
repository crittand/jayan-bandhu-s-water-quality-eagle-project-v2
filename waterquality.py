import hmac
import io
import math
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import folium
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
import seaborn as sns
import segno
import streamlit as st
from streamlit_folium import st_folium

import download_roseville_ceden_history as ceden
import download_esmr_usgs_history as other_sources
import site_data_store as store

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

matplotlib.use("Agg")

st.set_page_config(
    page_title="Dry Creek Water Quality Monitoring | Dry Creek Conservancy",
    page_icon="💧",
    layout="wide",
)

BASE_DIR = Path(__file__).parent



def safe_space(size: str = "small") -> None:
    # st.space only exists on newer streamlit versions
    if hasattr(st, "space"):
        try:
            st.space(size=size)
            return
        except Exception:
            pass
    px_height = 12 if size == "small" else 24
    st.markdown(f"<div style='height:{px_height}px'></div>", unsafe_allow_html=True)


# metric card font sizes
st.markdown(
    """
<style>
/* Adjust the big number value size */
[data-testid="stMetricValue"] {
    font-size: 20px;
}
/* Adjust the label text size above the number */
[data-testid="stMetricLabel"] {
    font-size: 14px; /* was 6px, way too small */
}
/* Adjust the delta text size below the number */
[data-testid="stMetricDelta"] {
    font-size: 10px;
}
</style>
""",
    unsafe_allow_html=True,
)

if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0


# --- historical data (only the Historical tab uses this) ---
# the download / cleanup code is in the 2 downloader scripts so the app and the command line do the same thing
#   download_roseville_ceden_history.py -> CEDEN
#   download_esmr_usgs_history.py  -> eSMR (roseville wwtp's) + USGS
@st.cache_data(show_spinner=False)
def load_history_file(kind: str, path_str: str, modified: float) -> pd.DataFrame:
    # `modified` is only there so the cache resets when a newer file shows up
    df = pd.read_csv(path_str, low_memory=False)
    if kind == "ceden":
        df = other_sources.ceden_to_unified(df)
    df["SampleDate"] = pd.to_datetime(df["SampleDate"], errors="coerce")
    df["Result"] = pd.to_numeric(df["Result"], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def ceden_year_tables() -> list[dict]:
    return ceden.list_year_tables()


@st.cache_data(ttl=3600, show_spinner=False)
def esmr_year_tables() -> list[dict]:
    return other_sources.esmr_year_tables()


# --- load data ---
# real field + lab files from the first repo. DONT edit these, the app only reads them
# (the old demo csvs sitting in Raw_data/ aren't used anymore)
REAL_DATA_DIR = BASE_DIR / "Raw_data" / "original"
qpcr = pd.read_csv(REAL_DATA_DIR / "QPCR.csv")
data = pd.read_csv(REAL_DATA_DIR / "Waterquality.csv").dropna(how="all")
data.columns = data.columns.str.strip()

# JV assay codes -> species names
ASSAY_NAMES = {
    "NZMudSnail": "New Zealand Mudsnail (Potamopyrgus antipodarum)",
    "AsianClam": "Asian Clam (Corbicula fluminea)",
    "Corbicula": "Asian Clam (Corbicula fluminea)",
}


def assay_species(code: str) -> str:
    for prefix, name in ASSAY_NAMES.items():
        if str(code).lower().startswith(prefix.lower()):
            return name
    return str(code)


qpcr["Species"] = qpcr["Assay"].apply(assay_species)


# partner uploads (Raw_data/community/). data_version() changes when a file does, so the cache refreshes
@st.cache_data(show_spinner=False)
def load_community(version):
    return store.load_sites(), store.load_samples()


sites_df, community = load_community(store.data_version())
_orig = data.assign(Organization="Dry Creek Conservancy", UploadBatch="original field data")
all_samples = pd.concat([_orig, community], ignore_index=True)    # every site, every org
all_samples["Site"] = all_samples["Site"].astype(str).str.strip().str.upper()
# concat with an empty/partly empty upload table turns the numbers into object dtype -> regplot etc blow up. force them back
for _c in store.PARAMS + ["Air Temp(C)", "DO(pct)"]:
    all_samples[_c] = pd.to_numeric(all_samples[_c], errors="coerce")
# the older tabs are built around our 2 sites, so they get JBDC01/02 rows (original + anything appended later)
data = all_samples[all_samples["Site"].isin(["JBDC01", "JBDC02"])].copy()


# --- alerts ---
def send_alerts(df: pd.DataFrame) -> list[str]:
    alerts = []
    if df.empty:
        return alerts
    latest = df.iloc[-1]
    site_label = "Miners Ravine (JBDC01)" if latest.get("Site") == "JBDC01" else "Saugstad Park / Dry Creek (JBDC02)"
    if latest["DO"] < 7:
        alerts.append(f"{site_label}: Low Dissolved Oxygen ({latest['DO']} mg/L < 7.0 mg/L salmonid threshold)")
    if latest["SPC"] > 500:
        alerts.append(f"{site_label}: High Specific Conductance ({latest['SPC']} µS/cm > 500 µS/cm)")
    if latest["Turbidity"] > 10:
        alerts.append(f"{site_label}: Elevated Turbidity ({latest['Turbidity']} NTU > 10 NTU clear-water baseline)")
    if latest["Water Temp"] > 20:
        alerts.append(f"{site_label}: Elevated Water Temp ({latest['Water Temp']} °C > 20 °C salmonid limit)")
    if latest["PH"] < 6.5 or latest["PH"] > 8.5:
        alerts.append(f"{site_label}: pH outside Basin Plan range ({latest['PH']} not in 6.5–8.5)")
    return alerts


# --- green/yellow/red bands for the plotly charts ---
THRESHOLD_ZONES = {
    "DO": {
        "title": "Dissolved Oxygen (DO) — How Much Breathable Oxygen Is in the Creek?",
        "unit": "mg/L",
        "ylim": (4, 12),
        "bands": [
            (4.0, 6.0, "rgba(234, 67, 53, 0.22)", "Red Zone: Unhabitable / Critical (<6 mg/L)"),
            (6.0, 7.0, "rgba(249, 171, 0, 0.22)", "Yellow Zone: Stressed for Salmon (6–7 mg/L)"),
            (7.0, 12.0, "rgba(52, 168, 83, 0.20)", "Green Zone: Healthy Salmonid Habitat (>=7 mg/L)"),
        ],
    },
    "SPC": {
        "title": "Specific Conductance (SPC) — Dissolved Minerals & Urban Storm Runoff",
        "unit": "µS/cm",
        "ylim": (0, 500),
        "bands": [
            (0, 200, "rgba(52, 168, 83, 0.20)", "Green Zone: Healthy Baseline (<200 µS/cm)"),
            (200, 300, "rgba(249, 171, 0, 0.22)", "Yellow Zone: Moderate / Urban Runoff (200–300 µS/cm)"),
            (300, 500, "rgba(234, 67, 53, 0.22)", "Red Zone: High Dissolved Ions (>300 µS/cm)"),
        ],
    },
    "Turbidity": {
        "title": "Turbidity — How Clear or Cloudy Is the Water?",
        "unit": "NTU",
        "ylim": (0, 100),
        "bands": [
            (0, 10, "rgba(52, 168, 83, 0.20)", "Green Zone: Clear Water (<10 NTU)"),
            (10, 50, "rgba(249, 171, 0, 0.22)", "Yellow Zone: Cloudy / Post-Storm Runoff (10–50 NTU)"),
            (50, 100, "rgba(234, 67, 53, 0.22)", "Red Zone: Opaque / Impaired (>50 NTU)"),
        ],
    },
    "PH": {
        "title": "pH — Acidity vs. Alkalinity Balance",
        "unit": "pH Units",
        "ylim": (4, 10),
        "bands": [
            (4.0, 6.5, "rgba(234, 67, 53, 0.22)", "Red Zone: Too Acidic (<6.5)"),
            (6.5, 8.5, "rgba(52, 168, 83, 0.20)", "Green Zone: Healthy Basin Plan Range (6.5–8.5)"),
            (8.5, 10.0, "rgba(234, 67, 53, 0.22)", "Red Zone: Too Alkaline (>8.5)"),
        ],
    },
    "Water Temp": {
        "title": "Water Temperature — Cool Water Is Essential for Salmon & Steelhead",
        "unit": "°C",
        "ylim": (0, 30),
        "bands": [
            (0, 10, "rgba(234, 67, 53, 0.18)", "Cold (<10 °C)"),
            (10, 20, "rgba(52, 168, 83, 0.20)", "Green Zone: Sustainable Salmonid Range (10–20 °C)"),
            (20, 30, "rgba(234, 67, 53, 0.22)", "Red Zone: Thermal Stress for Salmon (>20 °C)"),
        ],
    },
}


def build_plotly_threshold_chart(df: pd.DataFrame, param: str, site_name: str):
    spec = THRESHOLD_ZONES[param]
    sorted_df = df.sort_values("Date")
    fig = go.Figure()

    for y0, y1, fill_rgba, zone_label in spec["bands"]:
        fig.add_hrect(
            y0=y0,
            y1=y1,
            fillcolor=fill_rgba,
            line_width=0,
            annotation_text=zone_label,
            annotation_position="top right",
            annotation_font_size=10,
        )

    fig.add_trace(
        go.Scatter(
            x=sorted_df["Date"],
            y=sorted_df[param],
            mode="lines+markers",
            name=f"{site_name} ({param})",
            line=dict(color="#1f2937", width=2.5),
            marker=dict(size=8, color="#1A73E8", line=dict(width=1.5, color="white")),
            hovertemplate=f"<b>{site_name}</b><br>Date: %{{x|%b %d, %Y}}<br>{param}: <b>%{{y}} {spec['unit']}</b><extra></extra>",
        )
    )
    fig.update_layout(
        title=f"{spec['title']} — {site_name}",
        xaxis_title="Sample Date",
        yaxis_title=f"{param} ({spec['unit']})",
        yaxis=dict(range=list(spec["ylim"])),
        height=320,
        margin=dict(l=20, r=20, t=45, b=20),
    )
    return fig


# --- PDF report ---
def pdf_download(prompt: str, miners_ravine: pd.DataFrame, dry_creek: pd.DataFrame) -> None:
    params = ["DO", "SPC", "Turbidity", "PH", "Water Temp"]
    sites = ["Miners Ravine", "Dry Creek"]
    parameter = ""
    site = ""
    for i in params:
        if i.lower() in prompt.lower():
            parameter = i
            break
    for x in sites:
        if x.lower() in prompt.lower():
            site = x
            break
    param = parameter
    if param == "" or site == "":
        st.warning(
            "Command not recognized. Include both a parameter (`DO`, `SPC`, `Turbidity`, `PH`, or `Water Temp`) "
            "and a site (`Miners Ravine` or `Dry Creek`), e.g. **'DO report for Miners Ravine'**."
        )
    else:
        pdf = io.BytesIO()
        doc = SimpleDocTemplate(pdf, pagesize=letter, rightMargin=40, leftMargin=40)
        styles = getSampleStyleSheet()
        text = []

        finaldf = miners_ravine.copy() if site == "Miners Ravine" else dry_creek.copy()
        finaldf = finaldf.sort_values("Date")
        fig3, ax3 = plt.subplots(figsize=(6.5, 3.8))
        sns.lineplot(data=finaldf, x="Date", y=parameter, marker="o", ax=ax3, color="#1A73E8")
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax3.set_title(
            f"Data report for {parameter} over a {len(finaldf[parameter])} sample period for the {site} site"
        )
        img_buffer = io.BytesIO()
        fig3.savefig(img_buffer, format="png", bbox_inches="tight")
        img_buffer.seek(0)

        if parameter == "DO":
            thresholdstr = (
                "DO less than 5.0 mg/L: Unhabitable | "
                "DO between 5.0 mg/L to 7.0 mg/L: Stressful | "
                "DO greater than 7.0 mg/L: Healthy"
            )
        elif parameter == "PH":
            thresholdstr = (
                "pH less than 6.5: Acidic | "
                "pH greater than 8.5: Alkaline | "
                "pH 6.5-8.5: Healthy"
            )
        elif parameter == "SPC":
            thresholdstr = (
                "Conductivity less than 200 uS/cm: Healthy | "
                "Conductivity from 200-500 uS/cm: Tolerable | "
                "Conductivity greater than 500 uS/cm: Unhealthy"
            )
        elif parameter == "Turbidity":
            thresholdstr = (
                "Turbidity less than 10 NTU: Healthy | "
                "Turbidity from 10-50 NTU: Stressed | "
                "Turbidity > 50 NTU: Unhealthy"
            )
        else:
            thresholdstr = (
                "Temperature from 10-20 C: Normal sustainable temperature | "
                "Temperature < 10 C: Cold | Temperature > 20 C: Warm (Thermal Stress)"
            )

        text.append(Paragraph(f"<b>Dry Creek Water Quality Monitoring Project — {site} ({param})</b>", styles["Title"]))
        text.append(Spacer(1, 12))
        text.append(
            Paragraph(
                "<b>Community & Scientific Partners:</b> Supporting the <b>Dry Creek Conservancy (DCC)</b> watershed "
                "stewardship mission in Roseville, CA. Field physiochemical equipment loaned by the <b>Sierra Streams Institute</b>; "
                "eDNA BMI metabarcoding processed by the <b>CALeDNA lab at UC Santa Cruz (UCSC)</b> (shared on <b>eDNA Explorer</b>) "
                "and invasive species qPCR analyzed by <b>Jonah Ventures Laboratory</b>.",
                styles["BodyText"],
            )
        )
        text.append(Spacer(1, 8))
        text.append(Paragraph(f"<b>Thresholds for {param}:</b> {thresholdstr}", styles["BodyText"]))
        text.append(Spacer(1, 16))
        text.append(Image(img_buffer, width=440, height=260))

        doc.build(text)
        pdf.seek(0)

        st.download_button(
            label=f"⬇️ Download {site} — {param} PDF Report",
            data=pdf.getvalue(),
            file_name=f"{site.replace(' ', '_')}_{param.replace(' ', '_')}_Report.pdf",
            mime="application/pdf",
            type="primary",
        )
        if st.checkbox("View Chart Preview", value=True):
            st.pyplot(fig3)


# --- CEDEN-style export ---
# one row per reading, column + analyte names from the state's CEDEN data dictionary.
# this is NOT the official submission template (that comes from ceden.org), just a head start
def convert_samples_to_ceden2(df: pd.DataFrame) -> pd.DataFrame:
    station_lookup = {
        "JBDC01": {
            "StationCode": "519MINR_JBDC01",
            "StationName": "Miners Ravine — DCC Monitoring Station JBDC01 (Roseville)",
            "Lat": 38.752945,
            "Lon": -121.241526,
        },
        "JBDC02": {
            "StationCode": "519DRYC_JBDC02",
            "StationName": "Dry Creek at Saugstad Park — DCC Monitoring Station JBDC02 (Roseville)",
            "Lat": 38.742738,
            "Lon": -121.284156,
        },
    }
    param_lookup = {
        # names/units exactly how they show up in the published CEDEN tables
        "DO": ("Oxygen, Dissolved, Total", "mg/L"),
        "SPC": ("SpecificConductivity, Total", "uS/cm"),
        "Turbidity": ("Turbidity, Total", "NTU"),
        "Water Temp": ("Temperature", "Deg C"),
        "PH": ("pH", "none"),
    }
    ceden_rows = []
    for _, row in df.iterrows():
        site_code = str(row.get("Site", "JBDC01")).strip()
        st_meta = station_lookup.get(
            site_code,
            {"StationCode": site_code, "StationName": f"Roseville Station {site_code}", "Lat": 38.75, "Lon": -121.26},
        )
        sample_dt = pd.to_datetime(row["Date"]).strftime("%Y-%m-%d")
        for col_key, (analyte_name, unit) in param_lookup.items():
            if col_key in row and pd.notna(row[col_key]):
                ceden_rows.append(
                    {
                        "Program": "Dry Creek Conservancy Citizen Science Monitoring",
                        "ParentProject": "CEDEN_Dry_Creek_Watershed_Roseville",
                        "Project": "Dry Creek Conservancy Water Quality Monitoring",
                        "StationCode": st_meta["StationCode"],
                        "StationName": st_meta["StationName"],
                        "SampleDate": sample_dt,
                        # CEDEN 'unknown' defaults for stuff our field sheet doesnt have yet
                        "CollectionTime": "00:00",
                        "Analyte": analyte_name,
                        "MatrixName": "samplewater",
                        "MethodName": "Not Recorded",
                        "Result": row[col_key],
                        "Unit": unit,
                        "MDL": -88,
                        "RL": -88,
                        "Latitude": st_meta["Lat"],
                        "Longitude": st_meta["Lon"],
                    }
                )
    return pd.DataFrame(ceden_rows)


# --- page layout ---
st.title("💧 Dry Creek Water Quality Monitoring")
st.caption(
    "A **Dry Creek Conservancy (DCC)** dashboard for staff, volunteers, and funding sponsors — "
    "Monthly **Physiochemical Monitoring** (equipment loaned from **Sierra Streams Institute**) & **eDNA** "
    "(**CALeDNA Lab at UCSC / eDNA Explorer** BMI Metabarcoding + **Jonah Ventures** Invasive Species qPCR)"
)

# --- salmon event banner ---
# change these for the next event. QR code gets made from "url" automatically
# TODO: maybe move this into a little config file so we dont have to touch the code
SALMON_EVENT = {
    "title": "2026 Salmon Homecoming",
    "when": "Sunday, November 8, 2026",
    "where": "Royer Park, Roseville",
    "url": "https://www.facebook.com/events/1332502405384391",
    "last_day": date(2026, 11, 8),
}


@st.cache_data(show_spinner=False)
def make_qr_png(url: str) -> bytes:
    # error="m" so it still scans when it's small / printed / screenshotted
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=8, border=2, dark="#0B2545")
    return buf.getvalue()


today_pacific = datetime.now(ZoneInfo("America/Los_Angeles")).date()  # streamlit cloud runs on UTC!!
if today_pacific <= SALMON_EVENT["last_day"]:
    with st.container(border=True):
        qr_col, txt_col = st.columns([1, 5], vertical_alignment="center")
        with qr_col:
            st.image(make_qr_png(SALMON_EVENT["url"]), width=140)
        with txt_col:
            st.markdown(f"#### 🐟 {SALMON_EVENT['title']}")
            st.markdown(
                f"**{SALMON_EVENT['when']} · {SALMON_EVENT['where']}**  \n"
                "Come watch Chinook salmon return to Dry Creek with the Dry Creek Conservancy! "
                "Scan the code with your phone camera, or use the button."
            )
            st.link_button("📅 Event details & RSVP on Facebook", SALMON_EVENT["url"], type="primary")

with st.sidebar:
    st.header("🧭 Dashboard Navigation")
    tab_names = [
        "Overview",
        "Dry Creek Conservancy (DCC) & Mission",
        "Dry creek",
        "Miners Ravine",
        "Monitoring Sites",
        "Comparative analysis",
        "Correlation analysis",
        "PDF & Data Download",
        "eDNA results",
        "Simulation",
        "Upload Data",
        "Historical Analysis",
    ]
    # the map on the Overview tab sets pending_tab when a marker is clicked
    if "pending_tab" in st.session_state:
        st.session_state.nav_tab = tab_names[st.session_state.pop("pending_tab")]
    if st.session_state.get("nav_tab") not in tab_names:
        st.session_state.nav_tab = tab_names[0]
    # using a key (instead of index=) so one click always switches the tab
    selected_tab = st.radio("Select Tab", tab_names, key="nav_tab")
    st.session_state.active_tab = tab_names.index(selected_tab)

    st.divider()
    st.markdown(
        "**🌲 Quick Guide to the 5 Vital Signs**\n"
        "*(Monthly sensors loaned by **Sierra Streams Institute**)*:\n"
        "- **DO (Dissolved Oxygen):** Breathable oxygen for salmon (`>= 7 mg/L` is healthy).\n"
        "- **Conductivity (SPC):** Dissolved minerals & urban storm runoff (`< 200 µS/cm` is healthy).\n"
        "- **pH:** Acidity/alkalinity balance (`6.5 – 8.5` is healthy).\n"
        "- **Turbidity:** Water clarity vs. mud/sediment (`< 10 NTU` is clear).\n"
        "- **Water Temp:** Cool water keeps salmon alive (`10 – 20 °C` is sustainable).\n\n"
        "**🧬 Two eDNA Tracks:**\n"
        "- **BMI Metabarcoding:** Processed by **CALeDNA Lab at UCSC**, shared on **eDNA Explorer**.\n"
        "- **Invasive qPCR:** **New Zealand Mudsnails** & **Asian Clams** analyzed by **Jonah Ventures**."
    )


miners_ravine = data[data["Site"] == "JBDC01"].copy()
dry_creek = data[data["Site"] == "JBDC02"].copy()

miners_ravine["Date"] = pd.to_datetime(miners_ravine["Date"], format="mixed")
dry_creek["Date"] = pd.to_datetime(dry_creek["Date"], format="mixed")
miners_ravine = miners_ravine.sort_values("Date")
dry_creek = dry_creek.sort_values("Date")


# ===========================================================================
# TAB 1: OVERVIEW
# ===========================================================================
if selected_tab == "Overview":
    st.header("🌊 Water Quality Dashboard for the Dry Creek Watershed (Roseville, CA)")

    # intro box
    st.info(
        "🌲 **About This Dashboard**\n\n"
        "- **Who is the Dry Creek Conservancy (DCC)?** Founded in 1995, the **Dry Creek Conservancy** is a local Roseville "
        "501(c)(3) non-profit organization that protects and restores the **101-square-mile Dry Creek Watershed** across Placer and "
        "Sacramento counties, where native **Fall-run Chinook Salmon** and threatened **Central Valley Steelhead Trout** return to spawn.\n"
        "- **What this dashboard is for:** Sharing DCC's creek monitoring results with staff, volunteers, and the funding sponsors who make the work possible.\n"
        "- **Two Monitoring Components (`JBDC01` Miners Ravine & `JBDC02` Dry Creek at Saugstad Park):**\n"
        "  1. **Physiochemical Monitoring (Sierra Streams Institute Equipment Loan):** Tracking of **Conductivity (`SPC`)**, "
        "**pH (`PH`)**, **Dissolved Oxygen (`DO`)**, **Water Temperature**, and **Turbidity** using professional water quality instruments "
        "loaned from the **Sierra Streams Institute**.\n"
        "  2. **Two-Part Environmental DNA (eDNA) Analysis:**\n"
        "     - **BMI Metabarcoding (CALeDNA Lab at UCSC & eDNA Explorer):** Studies how pollution-sensitive **Benthic Macroinvertebrates (BMIs)** "
        "are affected by the physical and chemical characteristics of the two creeks.\n"
        "     - **Quantitative Invasive Species qPCR (Jonah Ventures Laboratory):** Tests creek water for DNA from two potent invasive species—"
        "**New Zealand Mudsnails** (*Potamopyrgus antipodarum*) and **Asian Clams** (*Corbicula fluminea*)."
    )

    # quick numbers for sponsors (calculated from the files)
    all_dates = pd.to_datetime(data["Date"], format="mixed")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Monitoring Sites", data["Site"].nunique())
    k2.metric("Field Sampling Days", all_dates.dt.date.nunique())
    k3.metric("Date Range", f"{all_dates.min():%b %Y} – {all_dates.max():%b %Y}")
    k4.metric("eDNA qPCR Tests", len(qpcr))

    with st.expander("📖 How to Read This Dashboard in 30 Seconds (Click to Expand)", expanded=False):
        g1, g2, g3 = st.columns(3)
        with g1:
            st.markdown(
                "**1️⃣ Check the 5 Monthly Vital Sign Cards**\n"
                "Measured with **Sierra Streams Institute** sensors, each site shows its latest reading for **DO**, **Conductivity**, **pH**, "
                "**Turbidity**, and **Water Temp**. **Green badges** mean healthy conditions for salmon and pollution-sensitive BMIs; "
                "**Red/Gray badges** indicate thermal or stormwater stress."
            )
        with g2:
            st.markdown(
                "**2️⃣ Click Any Station on the Map**\n"
                "The interactive Roseville map shows **Miners Ravine (`JBDC01`)**, **Saugstad Park (`JBDC02`)**, and their "
                "**Confluence**. Clicking a circle marker on the map automatically jumps to that creek's detailed trend graphs!"
            )
        with g3:
            st.markdown(
                "**3️⃣ Explore eDNA (UCSC CALeDNA & Jonah Ventures)**\n"
                "Use the left sidebar to inspect **BMI metabarcoding & invasive qPCR** (New Zealand Mudsnails + Asian Clams), "
                "compare creeks side-by-side, or run a what-if **Simulation**. Historical data from other monitoring programs is in the "
                "**Historical Analysis** tab at the bottom."
            )

    # DCC photos - we have permission
    st.subheader("📷 Dry Creek & Its Salmon")
    photos = [
        (
            "dcc_dry_creek.jpg",
            "Dry Creek. Photo courtesy of Dry Creek Conservancy",
        ),
        (
            "dcc_salmon_survey_1.jpg",
            "A DCC volunteer holds a Chinook salmon during a fall salmon survey. Photo courtesy of Dry Creek Conservancy",
        ),
        (
            "dcc_salmon_survey_2.jpg",
            "DCC salmon survey volunteers with a returning Chinook. Photo courtesy of Dry Creek Conservancy",
        ),
    ]
    pic_cols = st.columns(3)
    for col, (fname, cap) in zip(pic_cols, photos):
        img_path = BASE_DIR / "images" / fname
        if img_path.exists():
            col.image(str(img_path), caption=cap)

    active_alerts = send_alerts(miners_ravine) + send_alerts(dry_creek)
    if active_alerts:
        with st.expander(f"⚠️ {len(active_alerts)} Latest Threshold Watch Alert(s)", expanded=True):
            for msg in active_alerts:
                st.warning(msg)

    safe_space("small")
    st.subheader("🐟 Site 1: Miners Ravine (`JBDC01`) — Upstream Salmon Spawning Tributary")
    st.caption(
        "Miners Ravine joins Secret Ravine and Antelope Creek in Roseville to form Dry Creek. Because it has more natural shade "
        "and less urban storm runoff, DCC tracks Miners Ravine as critical spawning and rearing habitat for Chinook salmon."
    )
    if not miners_ravine.empty:
        latest_row = miners_ravine.iloc[-1]
        latest_do = latest_row["DO"]
        latest_cond = latest_row["SPC"]
        latest_ph = latest_row["PH"]
        latest_turbidity = latest_row["Turbidity"]
        latest_temp = latest_row["Water Temp"]

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            do_healthy = (
                "Healthy > 7 (mg/l)"
                if latest_do >= 7
                else ("Tolerable" if 5 <= latest_do < 7 else "Stressed")
            )
            color = "normal" if latest_do >= 7 else ("off" if 5 <= latest_do < 7 else "inverse")
            st.metric(
                label="Dissolved Oxygen",
                value=f"{latest_do} mg/L",
                delta=do_healthy,
                delta_color=color,
                help="Fish breathe dissolved oxygen. Salmon need at least 7.0 mg/L to thrive.",
            )

        with col2:
            cond_healthy = (
                "Healthy <150 "
                if latest_cond <= 150
                else ("Moderate(150-500)" if 150 < latest_cond <= 500 else "Stressed(>500)")
            )
            color2 = "normal" if latest_cond <= 150 else ("off" if 150 < latest_cond <= 500 else "inverse")
            st.metric(
                label="Conductivity",
                value=f"{latest_cond} µS/cm",
                delta=cond_healthy,
                delta_color=color2,
                help="Measures dissolved salts/minerals. Spikes after rainstorms when urban street runoff enters the creek.",
            )
        with col3:
            ph_healthy = (
                "Normal: 6.5-8.5"
                if 6.5 <= latest_ph <= 8.5
                else ("Alkali" if latest_ph >= 8.5 else "Acidic")
            )
            color = "normal" if 6.5 <= latest_ph <= 8.5 else "inverse"
            st.metric(
                label="PH",
                value=f"{latest_ph}",
                delta=ph_healthy,
                delta_color=color,
                help="Measures acidity vs. alkalinity. Aquatic life needs pH between 6.5 and 8.5.",
            )
        with col4:
            t_healthy = (
                "Clear <10NTU"
                if latest_turbidity <= 10
                else ("Cloudy" if latest_turbidity <= 50 else "Opaque")
            )
            color = "normal" if latest_turbidity <= 10 else ("off" if latest_turbidity <= 50 else "inverse")
            st.metric(
                label="Turbidity",
                value=f"{latest_turbidity} NTU",
                delta=t_healthy,
                delta_color=color,
                help="Measures water clarity. Under 10 NTU is clear; high turbidity means suspended mud, silt, or algae.",
            )
        with col5:
            temp_healthy = (
                "Sustainable"
                if 10 <= latest_temp <= 20
                else ("Hot" if latest_temp > 20 else "Cold")
            )
            color = "normal" if 10 <= latest_temp <= 21 else "inverse"
            st.metric(
                label="Water temperature",
                value=f"{latest_temp} °C",
                delta=temp_healthy,
                delta_color=color,
                help="Salmon and steelhead are cold-water fish that experience thermal stress above 20 °C (68 °F).",
            )

    safe_space("medium")
    st.subheader("🏞️ Site 2: Saugstad Park — Mainstem Dry Creek (`JBDC02`)")
    st.caption(
        "Located downstream of the confluence in urban Roseville. Monitoring Saugstad Park helps the Dry Creek Conservancy "
        "see how city storm drains ('first flush' runoff) and warmer open-channel sun exposure affect Dry Creek."
    )
    if not dry_creek.empty:
        latest_row = dry_creek.iloc[-1]
        latest_do = latest_row["DO"]
        latest_cond = latest_row["SPC"]
        latest_ph = latest_row["PH"]
        latest_turbidity = latest_row["Turbidity"]
        latest_temp = latest_row["Water Temp"]

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            do_healthy = (
                "Healthy > 7 (mg/l)"
                if latest_do >= 7
                else ("Tolerable" if 5 <= latest_do < 7 else "Stressed")
            )
            color = "normal" if latest_do >= 7 else ("off" if 5 <= latest_do < 7 else "inverse")
            st.metric(
                label="Dissolved Oxygen",
                value=f"{latest_do} mg/L",
                delta=do_healthy,
                delta_color=color,
                help="Fish breathe dissolved oxygen. Salmon need at least 7.0 mg/L to thrive.",
            )

        with col2:
            cond_healthy = (
                "Healthy <150 "
                if latest_cond <= 150
                else ("Moderate(150-500)" if 150 < latest_cond <= 500 else "Stressed(>500)")
            )
            color2 = "normal" if latest_cond <= 150 else ("off" if 150 < latest_cond <= 500 else "inverse")
            st.metric(
                label="Conductivity",
                value=f"{latest_cond} µS/cm",
                delta=cond_healthy,
                delta_color=color2,
                help="Measures dissolved salts/minerals. Spikes after rainstorms when urban street runoff enters the creek.",
            )
        with col3:
            ph_healthy = (
                "Normal: 6.5-8.5"
                if 6.5 <= latest_ph <= 8.5
                else ("Alkali" if latest_ph >= 8.5 else "Acidic")
            )
            color = "normal" if 6.5 <= latest_ph <= 8.5 else "inverse"
            st.metric(
                label="PH",
                value=f"{latest_ph}",
                delta=ph_healthy,
                delta_color=color,
                help="Measures acidity vs. alkalinity. Aquatic life needs pH between 6.5 and 8.5.",
            )
        with col4:
            t_healthy = (
                "Clear <10NTU"
                if latest_turbidity <= 10
                else ("Cloudy" if latest_turbidity <= 50 else "Opaque")
            )
            color = "normal" if latest_turbidity <= 10 else ("off" if latest_turbidity <= 50 else "inverse")
            st.metric(
                label="Turbidity",
                value=f"{latest_turbidity} NTU",
                delta=t_healthy,
                delta_color=color,
                help="Measures water clarity. Under 10 NTU is clear; high turbidity means suspended mud, silt, or algae.",
            )
        with col5:
            temp_healthy = (
                "Sustainable"
                if 10 <= latest_temp <= 20
                else ("Hot" if latest_temp > 20 else "Cold")
            )
            color = "normal" if 10 <= latest_temp <= 21 else "inverse"
            st.metric(
                label="Water temperature",
                value=f"{latest_temp} °C",
                delta=temp_healthy,
                delta_color=color,
                help="Salmon and steelhead are cold-water fish that experience thermal stress above 20 °C (68 °F).",
            )

    miners_lat = miners_ravine.iloc[-1]
    miners_ravine_health = (
        miners_lat["DO"] > 7
        and 6.5 < miners_lat["PH"] < 8.5
        and miners_lat["Turbidity"] < 10
        and miners_lat["Water Temp"] < 20
        and miners_lat["SPC"] < 200
    )
    dry_lat = dry_creek.iloc[-1]
    dry_creek_health = (
        dry_lat["DO"] > 7
        and 6.5 < dry_lat["PH"] < 8.5
        and dry_lat["Turbidity"] < 10
        and dry_lat["Water Temp"] < 20
        and dry_lat["SPC"] < 200
    )
    miners_status = "Healthy" if miners_ravine_health else "Stressed"
    dry_status = "Healthy" if dry_creek_health else "Stressed"

    safe_space("small")
    st.subheader("🗺️ Dry Creek Watershed Monitoring Site Map (Click a Marker to Open Site Tab)")
    st.caption(
        "**Green Marker** = All 5 vital signs are within ideal targets on the latest sample date. "
        "**Red Marker** = One or more parameters (such as summer temperature or storm turbidity) are in the watch/stressed zone. "
        "**Gray Marker** = Reference point with no samples."
    )
    # Note: Tab index 2 = "Dry creek", Tab index 3 = "Miners Ravine"
    mapdata = pd.DataFrame(
        {
            "latitude": [38.752945, 38.742738, 38.759216],
            "longitude": [-121.241526, -121.284156, -121.256444],
            "label": ["Miners Ravine (JBDC01)", "Saugstad Park (JBDC02)", "Confluence"],
            "fill": [
                "green" if miners_status == "Healthy" else "red",
                "green" if dry_status == "Healthy" else "red",
                "gray",
            ],
            "health_status": [miners_status, dry_status, "Reference point (not sampled)"],
            "Tab": [3, 2, 2],
        }
    )
    fmap = folium.Map(location=[38.751, -121.262], zoom_start=13)
    for _, row in mapdata.iterrows():
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=10,
            color=row["fill"],
            popup=f"Click to view {row['label']} Data",
            fill=True,
            fill_color=row["fill"],
            fill_opacity=0.85,
            tooltip=f"{row['label']} status: {row['health_status']}",
        ).add_to(fmap)
    map_out = st_folium(fmap, height=420, width=720)
    if map_out and map_out.get("last_object_clicked"):
        clicked_lat = map_out.get("last_object_clicked")["lat"]
        match = mapdata[abs(mapdata["latitude"] - clicked_lat) < 0.001].dropna()
        if not match.empty:
            target_tab = int(match.iloc[0]["Tab"])
            if st.session_state.active_tab != target_tab:
                st.session_state.pending_tab = target_tab
                st.rerun()


# ===========================================================================
# TAB 2: DRY CREEK CONSERVANCY (DCC) & MISSION
# ===========================================================================
elif selected_tab == "Dry Creek Conservancy (DCC) & Mission":
    st.header("🌲 What Is the Dry Creek Conservancy (DCC) & How This Project Ties In")

    st.markdown(
        """
### 1. Who Is the Dry Creek Conservancy (DCC)?
Founded in **1995**, the **[Dry Creek Conservancy (DCC)](https://drycreekconservancy.org/)** is a grassroots 501(c)(3) non-profit watershed stewardship organization based in **Roseville, California**. For three decades, DCC has brought together students, citizen scientists, local residents, resource agencies, and cities to protect and restore the **101-square-mile Dry Creek Watershed** spanning south Placer County and north Sacramento County.

#### Key Waterways Protected by DCC in Roseville & Placer County:
* **Secret Ravine & Miner's Ravine**: Lush foothill tributaries feeding into Roseville that provide cool, gravelly spawning beds (*redds*) for native **Fall-run Chinook Salmon** and federally threatened **Central Valley Steelhead Trout**.
* **Antelope Creek & Linda Creek**: Crucial urban/suburban tributaries supporting riparian wildlife corridors, native oaks, and flood-control open space.
* **Mainstem Dry Creek (including Royer Park & Saugstad Park)**: Forms right in Roseville where Miner's Ravine, Secret Ravine, and Antelope Creek meet, flowing southwest through Sacramento County toward the Sacramento River.
"""
    )

    map_img = BASE_DIR / "images" / "dcc_watershed_map.jpg"
    if map_img.exists():
        st.image(str(map_img), caption="Dry Creek sub-watersheds. Map courtesy of Dry Creek Conservancy", width=700)

    st.divider()
    st.subheader("🤝 2. How This Monitoring Program Supports DCC's 4 Core Pillars")

    p1_col, p2_col = st.columns(2)
    with p1_col:
        st.markdown(
            """
#### 🐟 Pillar A: Protecting Salmon & Steelhead Spawning Habitat
Every autumn and winter (November–January), DCC volunteers walk the creeks to count returning Chinook salmon and spawning nests. However, salmon eggs and juvenile fish (*fry*) can only survive if the water remains **cool (`10–20 °C`)** and **oxygen-rich (`DO >= 7.0 mg/L`)**.
* **Program Tie-In:** By regularly monitoring **Miners Ravine (`JBDC01`)** and **Dry Creek at Saugstad Park (`JBDC02`)**, this dashboard gives DCC, its sponsors, and the public a clear visual report card on whether water temperatures and dissolved oxygen stay inside the safe green survival zone for salmon.

#### 🌧️ Pillar B: Tracking Urban "First Flush" Stormwater Runoff
As Roseville grows, rainstorms wash tire dust, fertilizers, road salts, and silt off paved streets into storm drains that empty directly into the creeks.
* **Program Tie-In:** Comparing upstream **Miners Ravine (`JBDC01`)** against downstream **Saugstad Park (`JBDC02`)** will show how urban runoff affects **Specific Conductance (`SPC`)** and **Turbidity** once storm-season samples are collected.
"""
        )

    with p2_col:
        st.markdown(
            """
#### 🧬 Pillar C: Two-Track eDNA Bioassessment & Invasive Species Modeling
Healthy creeks rely on pollution-sensitive **Benthic Macroinvertebrates (BMIs)**—native aquatic insect larvae like mayflies, stoneflies, and caddisflies that feed juvenile salmon—while invasive mollusks threaten to disrupt the food web.
* **eDNA Track 1 — BMI Metabarcoding (`CALeDNA Lab at UCSC` & `eDNA Explorer`):** Conducted to understand how the presence of pollution-sensitive BMI organisms is affected by the water chemistry characteristics of Miners Ravine (`JBDC01`) vs. Dry Creek (`JBDC02`). All metabarcoding is processed by the **CALeDNA lab at UC Santa Cruz (UCSC)** and shared publicly on **eDNA Explorer**.
* **eDNA Track 2 — Quantitative Invasive Species qPCR (`Jonah Ventures Laboratory`):** Quantitative qPCR assays test for **two potent invasive species**—**New Zealand Mudsnails (*Potamopyrgus antipodarum*)** and **Asian Clams (*Corbicula fluminea*)**—analyzed by the **Jonah Ventures laboratory**. Current results are on the **eDNA results** tab.

#### ☁️ Pillar D: Sierra Streams Institute Field Sensors
All physiochemical monitoring equipment (`DO`, `SPC`, `PH`, `Turbidity`, `Water Temp`) is loaned from the **Sierra Streams Institute**. Historical data from other monitoring programs (state, USGS, and Roseville's wastewater plants) is kept separate in the **Historical Analysis** tab at the end.
"""
        )
        test_img = BASE_DIR / "images" / "dcc_creek_water_testing.jpg"
        if test_img.exists():
            st.image(str(test_img), caption="Testing the creek water. Photo courtesy of Dry Creek Conservancy")

    st.divider()
    st.subheader("🔬 3. Scientific, Laboratory & Watershed Partners")
    partners_df = pd.DataFrame(
        [
            {
                "Partner Organization": "Dry Creek Conservancy (DCC)",
                "Role in Monitoring Program": "Watershed Stewardship & Community Partner (Roseville, CA)",
                "Component Supported": "101-sq-mi Dry Creek Watershed restoration, Chinook salmon & Steelhead habitat protection",
            },
            {
                "Partner Organization": "Sierra Streams Institute",
                "Role in Monitoring Program": "Field Monitoring Equipment Loan Partner",
                "Component Supported": "Monthly physiochemical sensors for Conductivity (SPC), pH, Dissolved Oxygen (DO), Temperature & Turbidity",
            },
            {
                "Partner Organization": "CALeDNA Lab at UC Santa Cruz (UCSC) & eDNA Explorer",
                "Role in Monitoring Program": "Metabarcoding Sequencing Lab & Open Data Platform",
                "Component Supported": "Monthly BMI metabarcoding to study how pollution-sensitive organisms respond to creek water chemistry",
            },
            {
                "Partner Organization": "Jonah Ventures Laboratory",
                "Role in Monitoring Program": "Quantitative qPCR Molecular Analysis Laboratory",
                "Component Supported": "Quantitative qPCR assays modeling the spread of invasive New Zealand Mudsnails & Asian Clams",
            },
        ]
    )
    st.dataframe(partners_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📊 4. Quick Reference: What Do the 5 Water Quality Vital Signs Mean?")
    ref_df = pd.DataFrame(
        [
            {
                "Vital Sign": "Dissolved Oxygen (DO)",
                "Healthy Green Zone": ">= 7.0 mg/L",
                "Watch / Yellow Zone": "5.0 – 7.0 mg/L",
                "Red / Impaired Zone": "< 5.0 mg/L",
                "Why DCC Cares (Plain English)": "Oxygen dissolved in water that fish and native aquatic bugs breathe.",
            },
            {
                "Vital Sign": "Water Temperature",
                "Healthy Green Zone": "10 – 20 °C (50–68 °F)",
                "Watch / Yellow Zone": "< 10 °C (Winter Cold)",
                "Red / Impaired Zone": "> 20 °C (> 68 °F)",
                "Why DCC Cares (Plain English)": "Warm water (>20 °C) stresses cold-water Chinook salmon and holds less oxygen.",
            },
            {
                "Vital Sign": "Specific Conductance (SPC)",
                "Healthy Green Zone": "< 200 µS/cm",
                "Watch / Yellow Zone": "200 – 300 µS/cm",
                "Red / Impaired Zone": "> 300 – 500 µS/cm",
                "Why DCC Cares (Plain English)": "Measures dissolved ions/salts; jumps when urban street runoff ('first flush') enters creeks.",
            },
            {
                "Vital Sign": "Turbidity (Clarity)",
                "Healthy Green Zone": "< 10 NTU (Clear)",
                "Watch / Yellow Zone": "10 – 50 NTU (Cloudy)",
                "Red / Impaired Zone": "> 50 NTU (Muddy/Opaque)",
                "Why DCC Cares (Plain English)": "High mud/silt clogs salmon gravel nests (redds) and blocks sunlight.",
            },
            {
                "Vital Sign": "pH (Acidity / Alkalinity)",
                "Healthy Green Zone": "6.5 – 8.5",
                "Watch / Yellow Zone": "Near 6.5 or 8.5 edge",
                "Red / Impaired Zone": "< 6.5 or > 8.5",
                "Why DCC Cares (Plain English)": "Creek water must stay near neutral (6.5–8.5) so fish gills and insect shells aren't harmed.",
            },
        ]
    )
    st.dataframe(ref_df, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 3 & TAB 4: DRY CREEK & MINERS RAVINE SITE TRENDS
# ===========================================================================
elif selected_tab in ("Dry creek", "Miners Ravine"):
    is_dry = selected_tab == "Dry creek"
    site_df = dry_creek if is_dry else miners_ravine
    site_label = "Dry Creek (Saugstad Park — JBDC02)" if is_dry else "Miners Ravine (JBDC01)"

    st.subheader(f"📈 Parameter Trends — {site_label}")
    if is_dry:
        st.info(
            "🏞️ **About Saugstad Park (`JBDC02`):** Located on mainstem **Dry Creek** in Roseville downstream of where "
            "Miners Ravine and Antelope Creek meet. As storm-season samples come in, these charts will show how "
            "**Conductivity (`SPC`)** and **Turbidity** respond to urban storm drain runoff."
        )
    else:
        st.info(
            "🐟 **About Miners Ravine (`JBDC01`):** A foothill tributary in Roseville monitored by the **Dry Creek Conservancy** "
            "for **Fall-run Chinook Salmon** and **Steelhead** spawning. Use the **Comparative analysis** tab to see how it "
            "lines up against downstream Saugstad Park."
        )
    st.caption(f"Based on {len(site_df)} field samples ({site_df['Date'].min():%b %d, %Y} – {site_df['Date'].max():%b %d, %Y}).")
    st.caption(
        "🎨 **How to Read the Shaded Colors:** 🟩 **Green Band** = Healthy target range for salmon & creek life | "
        "🟨 **Yellow Band** = Moderate / Watch range | 🟥 **Red Band** = Stressed or impaired range."
    )

    if HAS_PLOTLY:
        chart_mode = st.radio(
            "Chart Engine",
            ["Interactive Plotly Shaded Zones", "Classic Matplotlib / Seaborn Shaded Zones"],
            horizontal=True,
        )
    else:
        chart_mode = "Classic Matplotlib / Seaborn Shaded Zones"

    if chart_mode == "Interactive Plotly Shaded Zones" and HAS_PLOTLY:
        for param_key in ["DO", "SPC", "Turbidity", "PH", "Water Temp"]:
            st.plotly_chart(
                build_plotly_threshold_chart(site_df, param_key, site_label),
                use_container_width=True,
            )
    else:
        fig4, ax4 = plt.subplots()
        sns.lineplot(data=site_df, x="Date", y="DO", ax=ax4, marker="o", color="black")
        ax4.set_title(f"DO trend for {site_label}")
        ax4.set_ylim(5, 11)
        ax4.axhspan(5, 6, color="red", alpha=0.35)
        ax4.axhspan(6, 7, color="yellow", alpha=0.35)
        ax4.axhspan(7, 11, color="green", alpha=0.30)
        ax4.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        st.pyplot(fig4)

        safe_space("small")
        fig5, ax5 = plt.subplots()
        sns.lineplot(data=site_df, x="Date", y="SPC", ax=ax5, marker="o", color="black")
        ax5.set_title(f"Conductivity trends for {site_label}")
        ax5.set_ylim(0, 500)
        ax5.axhspan(300, 500, color="red", alpha=0.35)
        ax5.axhspan(200, 300, color="yellow", alpha=0.35)
        ax5.axhspan(0, 200, color="green", alpha=0.30)
        ax5.set_xlabel("Date")
        ax5.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        st.pyplot(fig5)

        safe_space("small")
        fig6, ax6 = plt.subplots()
        sns.lineplot(data=site_df, x="Date", y="Turbidity", ax=ax6, marker="o", color="black")
        ax6.set_title(f"Turbidity trends for {site_label}")
        ax6.set_ylim(0, 100)
        ax6.axhspan(50, 100, color="red", alpha=0.35)
        ax6.axhspan(10, 50, color="yellow", alpha=0.35)
        ax6.axhspan(0, 10, color="green", alpha=0.30)
        ax6.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        st.pyplot(fig6)

        safe_space("small")
        figph, axph = plt.subplots()
        sns.lineplot(data=site_df, x="Date", y="PH", ax=axph, marker="o", color="black")
        axph.set_title(f"pH trends for {site_label}")
        axph.set_ylim(4, 10)
        axph.axhspan(4, 6.5, color="red", alpha=0.35)
        axph.axhspan(8.5, 10, color="red", alpha=0.35)
        axph.axhspan(6.5, 8.5, color="green", alpha=0.30)
        axph.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        st.pyplot(figph)

        safe_space("small")
        temp, tempax = plt.subplots()
        sns.lineplot(data=site_df, x="Date", y="Water Temp", ax=tempax, marker="o", color="brown")
        tempax.set_title(f"Water temperature for {site_label}")
        tempax.set_ylim(0, 30)
        tempax.axhspan(0, 10, color="red", alpha=0.30)
        tempax.axhspan(10, 20, color="green", alpha=0.30)
        tempax.axhspan(20, 30, color="red", alpha=0.35)
        tempax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        st.pyplot(temp)


# ===========================================================================
# MONITORING SITES - every site, ours + whatever partners added through Upload Data
# ===========================================================================
elif selected_tab == "Monitoring Sites":
    st.header("📍 Monitoring Sites")
    st.caption("Every site on the dashboard: our JBDC01 / JBDC02 plus any site a partner group (or DCC) added through **📤 Upload Data**.")

    ms = all_samples.copy()
    ms["Date"] = pd.to_datetime(ms["Date"], format="mixed", errors="coerce")
    ms = ms.dropna(subset=["Date"])
    info = sites_df.copy()
    info["SiteCode"] = info["SiteCode"].astype(str).str.upper()
    # data for a site that somehow isnt registered still shows up
    for c in sorted(set(ms["Site"]) - set(info["SiteCode"])):
        info.loc[len(info)] = {"SiteCode": c, "SiteName": c, "Organization": ms.loc[ms["Site"] == c, "Organization"].iloc[0]}
    name_of = dict(zip(info["SiteCode"], info["SiteName"].fillna(info["SiteCode"])))
    org_of = dict(zip(info["SiteCode"], info["Organization"]))

    def site_label(code):
        return f"{code} · {name_of.get(code, code)}"

    orgs = sorted(info["Organization"].dropna().unique())
    # pills get their own row, org names are long and were getting cut off in a column
    org_pick = st.pills("Organization", orgs, selection_mode="multi", default=orgs) or []
    codes_avail = info.loc[info["Organization"].isin(org_pick), "SiteCode"].tolist()
    site_pick = st.multiselect("Sites", codes_avail, default=codes_avail, format_func=site_label)

    sub = ms[ms["Site"].isin(site_pick)].sort_values("Date")
    sub = sub.assign(SiteLabel=sub["Site"].map(site_label))

    def health(row):
        # same rule as the overview map, but only checks what the site actually measures
        checks = []
        if pd.notna(row.get("DO")): checks.append(row["DO"] > 7)
        if pd.notna(row.get("PH")): checks.append(6.5 < row["PH"] < 8.5)
        if pd.notna(row.get("Turbidity")): checks.append(row["Turbidity"] < 10)
        if pd.notna(row.get("Water Temp")): checks.append(row["Water Temp"] < 20)
        if pd.notna(row.get("SPC")): checks.append(row["SPC"] < 200)
        if not checks:
            return "No data"
        return "Healthy" if all(checks) else "Stressed"

    if not site_pick:
        st.info("Pick at least one organization / site above.")
    else:
        latest = sub.groupby("Site").tail(1).set_index("Site")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Sites", len(site_pick))
        k2.metric("Organizations", len({org_of.get(c) for c in site_pick}))
        k3.metric("Samples", f"{len(sub):,}")
        k4.metric("Latest sample", f"{sub['Date'].max():%b %d, %Y}" if len(sub) else "—")

        m_col, t_col = st.columns([1, 1])
        with m_col:
            smap = folium.Map(location=[38.80, -121.20], zoom_start=10)
            pts = []
            for code in site_pick:
                r = info[info["SiteCode"] == code].iloc[0]
                lat, lon = pd.to_numeric(r.get("Latitude"), errors="coerce"), pd.to_numeric(r.get("Longitude"), errors="coerce")
                if pd.isna(lat) or pd.isna(lon):
                    continue
                stat = health(latest.loc[code]) if code in latest.index else "No data"
                colr = {"Healthy": "green", "Stressed": "red"}.get(stat, "gray")
                folium.CircleMarker(location=[lat, lon], radius=9, color=colr, fill=True, fill_color=colr, fill_opacity=0.85,
                                    tooltip=f"{site_label(code)} ({r['Organization']}) · latest: {stat}").add_to(smap)
                pts.append([lat, lon])
            if len(pts) > 1:
                smap.fit_bounds(pts, padding=(30, 30))
            elif pts:
                smap.location = pts[0]
            st_folium(smap, height=380, use_container_width=True, returned_objects=[], key="sites_map")
            st.caption("🟢 latest sample healthy · 🔴 something in the watch/stressed range · ⚪ no data yet")
        with t_col:
            rows = []
            for code in site_pick:
                d_ = sub[sub["Site"] == code]
                rows.append({
                    "Site": code, "Name": name_of.get(code, code), "Organization": org_of.get(code, ""),
                    "Samples": len(d_), "First": f"{d_['Date'].min():%Y-%m-%d}" if len(d_) else "—",
                    "Last": f"{d_['Date'].max():%Y-%m-%d}" if len(d_) else "—",
                    "Latest": health(latest.loc[code]) if code in latest.index else "No data",
                })
            # height grows w/ the number of sites (max = map height) so theres no wall of empty rows
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(380, 38 + 35 * len(rows)))

        if sub.empty:
            st.info("No samples yet for the selected sites.")
        else:
            have = [p for p in store.PARAMS if sub[p].notna().any()]
            nice_p = {"DO": "💨 Dissolved Oxygen", "SPC": "⚡ Conductivity", "PH": "🧪 pH", "Turbidity": "🌫️ Turbidity", "Water Temp": "🌡️ Water Temp"}
            pp = st.segmented_control("Parameter", have, default=have[0], format_func=lambda c: nice_p.get(c, c), key="sites_param") or have[0]
            spec = THRESHOLD_ZONES[pp]

            tr_tab, box_tab, last_tab = st.tabs(["📈 Over time", "📦 Site vs site", "🔎 Latest reading"])
            with tr_tab:
                fig_s = px.line(sub.dropna(subset=[pp]), x="Date", y=pp, color="SiteLabel", markers=True,
                                hover_data={"Organization": True, "SiteLabel": False})
                for y0, y1, fill_rgba, _lab in spec["bands"]:
                    fig_s.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                fig_s.update_layout(height=430, yaxis_title=f"{pp} ({spec['unit']})", xaxis_title=None,
                                    legend=dict(orientation="h", y=-0.18, x=0, title=None), margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_s, use_container_width=True)
            with box_tab:
                fig_b = px.box(sub.dropna(subset=[pp]), x="SiteLabel", y=pp, color="Organization", points="all")
                for y0, y1, fill_rgba, _lab in spec["bands"]:
                    fig_b.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                fig_b.update_layout(height=430, xaxis_title=None, yaxis_title=f"{pp} ({spec['unit']})",
                                    legend=dict(orientation="h", y=-0.25, x=0), margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_b, use_container_width=True)
                st.caption("Each box = the middle half of that site's samples, line = median, dots = every sample.")
            with last_tab:
                one = st.selectbox("Site", site_pick, format_func=site_label, key="sites_latest")
                if one in latest.index:
                    lr = latest.loc[one]
                    st.caption(f"Latest sample: {lr['Date']:%B %d, %Y} · {org_of.get(one, '')}")

                    def zone(p_, v):
                        for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[p_]["bands"]:
                            if y0 <= v <= y1:
                                return "🟢 healthy" if "52, 168, 83" in fill_rgba else ("🟡 watch" if "249, 171, 0" in fill_rgba else "🔴 stressed")
                        return "outside chart range"

                    lc = st.columns(5)
                    for col, p_ in zip(lc, store.PARAMS):
                        v = lr.get(p_)
                        if pd.notna(v):
                            col.metric(p_, f"{v:g} {THRESHOLD_ZONES[p_]['unit'] if p_ != 'PH' else ''}".strip(), zone(p_, v), delta_color="off", border=True)
                        else:
                            col.metric(p_, "—", "not measured", delta_color="off", border=True)
                else:
                    st.caption("No samples for that site yet.")

            st.download_button("⬇️ Download these sites' data (CSV)",
                               sub.drop(columns=["SiteLabel"]).assign(Date=sub["Date"].dt.strftime("%Y-%m-%d")).to_csv(index=False).encode(),
                               "monitoring_sites_data.csv", "text/csv")


# ===========================================================================
# TAB 5: COMPARATIVE ANALYSIS
# ===========================================================================
elif selected_tab == "Comparative analysis":
    st.subheader("⚖️ Side-by-Side Creek Comparison (`JBDC01` Miners Ravine vs. `JBDC02` Dry Creek)")
    st.markdown(
        "Compare the upstream tributary (**Miners Ravine `JBDC01`**, shown in **Blue**) against the downstream urban park site "
        "(**Dry Creek at Saugstad Park `JBDC02`**, shown in **Gray**) to see how water quality changes as the creek flows through Roseville."
    )
    param = st.selectbox(
        label="Select a water quality parameter to compare",
        options=["DO", "SPC", "PH", "Turbidity", "Water Temp"],
        index=0,
    )

    fig, ax = plt.subplots(figsize=(8, 4.2))
    # both creeks on ONE axis now. the old twinx() gave each line its own y axis + its own legend
    # and the two legends were landing on top of each other
    y1 = miners_ravine[["Date", param]].sort_values(["Date"])
    y2 = dry_creek[["Date", param]].sort_values(["Date"])

    sns.lineplot(data=y1, x="Date", y=param, marker="o", color="blue", label="Miners Ravine (JBDC01)", ax=ax)
    sns.lineplot(data=y2, x="Date", y=param, marker="s", color="gray", label="Dry Creek / Saugstad (JBDC02)", ax=ax)

    if len(param) == 2:
        if param == "DO":
            ax.set_ylim(5, 11)
            ax.axhspan(5, 6, color="red", alpha=0.30)
            ax.axhspan(6, 7, color="yellow", alpha=0.30)
            ax.axhspan(7, 11, color="green", alpha=0.25)
        else:
            ax.set_ylim(3, 9)
            ax.axhspan(3, 6.5, color="red", alpha=0.30)
            ax.axhspan(6.5, 8.5, color="green", alpha=0.25)
            ax.axhspan(8.5, 9, color="red", alpha=0.30)
    elif len(param) == 3:
        ax.set_ylim(100, 300)
        ax.axhspan(0, 200, color="green", alpha=0.25)
        ax.axhspan(200, 300, color="yellow", alpha=0.30)
    elif param == "Turbidity":
        ax.set_ylim(0, 50)
        ax.axhspan(0, 10, color="green", alpha=0.25)
        ax.axhspan(10, 50, color="yellow", alpha=0.30)
    elif param == "Water Temp":
        ax.set_ylim(8, 28)
        ax.axhspan(10, 20, color="green", alpha=0.25)
        ax.axhspan(20, 28, color="red", alpha=0.30)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    # legend under the chart so it never sits on the lines
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2, frameon=False)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    if param == "DO":
        st.markdown("**What is DO (Dissolved Oxygen)?**")
        st.write(
            "Dissolved Oxygen is a measurement of oxygen dissolved in the water. Dissolved oxygen levels are key "
            "for local salmonids tracked by the Dry Creek Conservancy as well as all other creek-dwelling organisms. "
            "Dissolved oxygen levels depend on many factors, such as creek flow, bacteria, and water temperature. "
            "Diurnal variations in DO occur: in the afternoons, DO increases because photosynthesizing plants release "
            "oxygen during the day; DO decreases at night as organisms use up oxygen in cellular respiration."
        )
        st.markdown("**DO Thresholds**")
        st.write("• A DO level of **7 mg/L or greater** is considered satisfactory for cold-water fish like salmon and steelhead.")
        st.write("• A DO level between **5 mg/L and 7 mg/L** is considered stressed because it puts juvenile salmonids in distress and alters their ability to swim and nourish.")
        st.write("• A DO level **below 5 mg/L** is considered unsurvivable for most creek-dwelling organisms.")
    elif param == "PH":
        st.markdown("**What is pH?**")
        st.write("pH is a measure of acidity of the creek. An acidic pH can be caused by many factors, including pine needles or decomposing organic matter.")
        st.markdown("**pH Thresholds**")
        st.write("pH values should stay within **6.5 to 8.5** for a balance of alkalinity and acidity. Anywhere outside of this range is considered impaired.")
    elif param == "SPC":
        st.markdown("**Specific Conductance (SPC)**")
        st.write(
            "Specific Conductance is a measure of charged particles dissolved in the creek water. Conductivity "
            "generally varies from creek to creek based on the minerals located in the area. Short-term changes in "
            "conductivity tend to happen right after storm events. The first surge of conductivity after storm drain "
            "runoff in urban areas is called the **first flush**. This is commonly seen in urban areas, and is "
            "directly relevant to the Saugstad Park site which faces urbanization."
        )
        st.markdown("**Thresholds for Conductivity**")
        st.write("Conductivity numbers should not be above **500 µS/cm**. Generally, a healthy creek will have a conductivity **below 200 µS/cm**.")
    elif param == "Turbidity":
        st.markdown("**Turbidity**")
        st.write(
            "Turbidity is a measure of the physical clarity of creek water. Turbidity values can vary greatly after "
            "storm events or bank erosion. Large amounts of algae can also increase the turbidity of the water. "
            "Turbidity is a general indicator of surface-level pollution of a creek, making it an important vital sign."
        )
        st.markdown("**Turbidity Thresholds**")
        st.write("A clear creek should generally have a turbidity of **less than 10 NTU**. A muddy creek after a storm can have a turbidity between **10–50 NTU**, and anything greater than that points to an underlying issue.")
    elif param == "Water Temp":
        st.markdown("**Water Temperature**")
        st.write(
            "Water temperature is a key parameter that determines whether salmonids and other species will be able "
            "to survive in a creek. In the Dry Creek watershed, temperature varies greatly between summer and winter. "
            "Water temperature also plays a direct role in other parameters like Dissolved Oxygen and conductivity."
        )
        st.markdown("**Temperature Thresholds**")
        st.write("Water temperature should fall between a sustainable range of **10 °C to 20 °C**.")


# ===========================================================================
# TAB 6: CORRELATION ANALYSIS
# ===========================================================================
elif selected_tab == "Correlation analysis":
    st.title("🔗 How Do Water Quality Parameters Affect Each Other?")
    st.markdown(
        "**Plain-English Guide:** In nature, water quality measurements are connected! For example, **colder water holds more "
        "Dissolved Oxygen** than warm water (a **negative correlation**: as temperature goes up, oxygen goes down). "
        "Pick any two parameters below to see how strongly they move together at Miners Ravine and Dry Creek."
    )
    x = st.multiselect(
        label="Select two parameters to compare",
        options=["DO", "SPC", "Turbidity", "PH", "Water Temp"],
        max_selections=2,
        default=["DO", "Water Temp"],
    )
    if len(x) != 2:
        st.warning("Please select 2 parameters")
    else:
        p1, p2 = x
        miners = miners_ravine.copy()
        miners["Site Name"] = "Miners Ravine (JBDC01)"
        dry = dry_creek.copy()
        dry["Site Name"] = "Dry Creek / Saugstad (JBDC02)"
        new = pd.concat([miners, dry], ignore_index=True)

        fig2, ax2 = plt.subplots(figsize=(7.5, 4.2))
        sns.scatterplot(data=new, x=p1, y=p2, hue="Site Name", s=80, ax=ax2)
        sns.regplot(data=miners, x=p1, y=p2, scatter=False, ax=ax2, color="#1f77b4", line_kws={"linestyle": "--"})
        sns.regplot(data=dry, x=p1, y=p2, scatter=False, ax=ax2, color="#ff7f0e", line_kws={"linestyle": "--"})
        ax2.set_title(f"{p1} vs. {p2} Across Monitoring Sites")
        st.pyplot(fig2)

        minerscorr = miners_ravine[p1].corr(miners_ravine[p2])
        dry_creekcorr = dry_creek[p1].corr(dry_creek[p2])

        txt = "Strong" if abs(minerscorr) > 0.7 else ("medium" if abs(minerscorr) > 0.4 else "weak")
        txt2 = "Strong" if abs(dry_creekcorr) > 0.7 else ("medium" if abs(dry_creekcorr) > 0.4 else "weak")
        sign = "Negative" if minerscorr < 0 else "Positive"
        sign2 = "Positive" if dry_creekcorr > 0 else "Negative"

        st.info(f"**Miners Ravine (`JBDC01`)**: Correlation between **{p1}** and **{p2}** is **{sign}** and **{txt}** ($r = {minerscorr:.2f}$).")
        st.info(f"**Dry Creek (`JBDC02`)**: Correlation between **{p1}** and **{p2}** is **{sign2}** and **{txt2}** ($r = {dry_creekcorr:.2f}$).")
        if min(len(miners_ravine), len(dry_creek)) < 10:
            st.caption(
                f"Note: only {len(miners_ravine)} samples at JBDC01 and {len(dry_creek)} at JBDC02 so far. With this few points "
                "a correlation can look strong just by chance, so treat these as early signs, not conclusions."
            )


# ===========================================================================
# TAB 7: PDF & DATA DOWNLOAD
# ===========================================================================
elif selected_tab == "PDF & Data Download":
    st.subheader("📄 Printable PDF Report Generator (For DCC & Community Sharing)")
    st.markdown(
        "Type a simple request naming a **parameter** (`DO`, `SPC`, `Turbidity`, `PH`, or `Water Temp`) and a **site** "
        "(`Miners Ravine` or `Dry Creek`) to generate a formatted PDF handout with threshold explanations and trend charts."
    )
    userinput = st.text_input(
        label="Give a prompt for what parameter you want to download and which site you want to download.",
        value="DO report for Miners Ravine",
        help="Examples: 'DO report for Miners Ravine', 'SPC at Dry Creek', 'Turbidity for Miners Ravine'",
    )
    pdf_download(userinput, miners_ravine, dry_creek)

    # raw data downloads
    st.divider()
    st.subheader("💾 Download Field Sample Data")
    st.caption(
        "Field readings from `JBDC01` and `JBDC02`. The CEDEN-style version puts each reading on its own row and uses the "
        "column names, analyte names, and default values from the State Water Board's CEDEN data dictionary. It's a starting "
        "point for submitting to CEDEN; the official submission templates are at ceden.org."
    )
    ceden_converted = convert_samples_to_ceden2(data)
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="⬇️ Download Samples (CSV)",
            data=data.to_csv(index=False).encode("utf-8"),
            file_name="DCC_JBDC01_JBDC02_Samples.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            label="⬇️ Download Samples, CEDEN-style (CSV)",
            data=ceden_converted.to_csv(index=False).encode("utf-8"),
            file_name="DCC_JBDC01_JBDC02_CEDEN_style.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with st.expander("Preview CEDEN-style rows"):
        st.dataframe(ceden_converted.head(10), use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 8: eDNA RESULTS
# ===========================================================================
elif selected_tab == "eDNA results":
    st.header("🧬 eDNA Results: BMI Metabarcoding & Invasive Species qPCR")
    st.info(
        "🔬 **How the Two-Component eDNA Program Works:**\n\n"
        "1. **BMI Metabarcoding (`CALeDNA Lab at UCSC` → Shared on `eDNA Explorer`):**\n"
        "   - Used to understand how the presence of **pollution-sensitive Benthic Macroinvertebrates (BMIs)** "
        "(such as EPT taxa: *Ephemeroptera* mayflies, *Plecoptera* stoneflies, and *Trichoptera* caddisflies) is affected by "
        "the physiochemical characteristics (`DO`, `SPC`, `PH`, `Turbidity`, `Water Temp`) of **Miners Ravine (`JBDC01`)** and "
        "**Dry Creek at Saugstad Park (`JBDC02`)**.\n"
        "   - Samples are collected in the field, processed for metabarcoding by the "
        "**CALeDNA lab at UC Santa Cruz (UCSC)**, and published on **eDNA Explorer**.\n"
        "2. **Quantitative Invasive Species qPCR Assays (`Jonah Ventures Laboratory`):**\n"
        "   - Tests creek water for DNA from **two potent aquatic invasive species**:\n"
        "     - **New Zealand Mudsnails (*Potamopyrgus antipodarum*)**: Tiny armor-shelled snails that crowd out native BMI insects and starve juvenile salmon.\n"
        "     - **Asian Clams (*Corbicula fluminea*)**: Invasive filter-feeding bivalves that alter creek sediment chemistry and compete with native macroinvertebrates.\n"
        "   - All qPCR assays are analyzed by the **Jonah Ventures laboratory**."
    )
    safe_space("small")

    # works for whatever species end up in QPCR.csv later
    def qpcr_summary(species_word):
        rows = qpcr[qpcr["Species"].str.contains(species_word, case=False, na=False)]
        if rows.empty:
            return "No results yet", "Not in the current lab file", rows
        n_hits = int((rows["AvgCopyNum"] > 0).sum())
        value = "Not Detected" if n_hits == 0 else f"Detected in {n_hits} of {len(rows)}"
        batches = ", ".join(sorted(rows["BatchId"].astype(str).unique()))
        return value, f"{len(rows)} samples • Batch {batches}", rows

    snail_val, snail_note, snail_rows = qpcr_summary("Mudsnail")
    clam_val, clam_note, clam_rows = qpcr_summary("Clam")

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "1. BMI Metabarcoding (UCSC CALeDNA)",
        "See eDNA Explorer",
        "Processed at UCSC • Shared on eDNA Explorer",
        delta_color="off",
    )
    c2.metric("2a. New Zealand Mudsnail qPCR", snail_val, snail_note, delta_color="off")
    c3.metric("2b. Asian Clam qPCR", clam_val, clam_note, delta_color="off")
    safe_space("small")

    if not snail_rows.empty and (snail_rows["AvgCopyNum"] == 0).all():
        st.success(
            f"**Jonah Ventures qPCR Summary:** No **New Zealand Mudsnail** DNA was found in any of the "
            f"**{len(snail_rows)} samples** tested (0 copies in all 3 lab replicates of each sample)."
        )
    elif not snail_rows.empty:
        st.warning("**Jonah Ventures qPCR Summary:** New Zealand Mudsnail DNA was detected in at least one sample. See the table below.")
    if clam_rows.empty:
        st.caption("Asian Clam qPCR results will show here once they are added to the lab data file.")

    if not qpcr.empty:
        st.subheader("📋 Jonah Ventures qPCR Results")
        st.caption("`SampleId` is the lab's sample ID. `Rep1`–`Rep3` are DNA copies found in each lab replicate.")
        species_options = ["All Target Species"] + sorted(qpcr["Species"].dropna().unique().tolist())
        selected_species = st.selectbox("Filter by Invasive Species Target", options=species_options, index=0)
        filtered_qpcr = (
            qpcr if selected_species == "All Target Species" else qpcr[qpcr["Species"] == selected_species]
        )
        st.dataframe(filtered_qpcr, use_container_width=True, hide_index=True)
        qpcr_csv = qpcr.drop(columns=["Species"]).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download qPCR Results (CSV)",
            data=qpcr_csv,
            file_name="Dry_Creek_eDNA_qPCR_JonahVentures.csv",
            mime="text/csv",
            type="primary",
        )


# ===========================================================================
# TAB 9: SIMULATION
# ===========================================================================
elif selected_tab == "Simulation":
    st.header("🔬 Interactive 'What-If' Creek Simulation")
    st.markdown(
        "**How It Works:** What happens to **Dissolved Oxygen (`DO`)** if summer **Water Temperature** rises to 24 °C? "
        "Use the controls in the **left sidebar** to pick an input variable, drag the slider, and see the predicted impact "
        "based on a linear regression fitted to the **Miners Ravine (`JBDC01`)** and **Dry Creek (`JBDC02`)** measurements!"
    )

    no1 = ["Water Temp", "DO", "SPC", "PH", "Turbidity"]
    with st.sidebar:
        st.subheader("🎛️ Simulation Controls")
        p1 = st.selectbox(label="Select the independent variable to manipulate!", options=no1, index=0)
        remaining = [item for item in no1 if item != p1]
        yval = st.selectbox(label="Select the responding variable to measure", options=remaining, index=0)

        if p1 == "DO":
            sim_x = st.slider(label="Drag to change DO value (mg/L)", min_value=4.0, max_value=14.0, value=8.5, step=0.2)
        elif p1 == "SPC":
            sim_x = st.slider(label="Drag to change Conductivity (µS/cm)", min_value=50.0, max_value=500.0, value=185.0, step=10.0)
        elif p1 == "Turbidity":
            sim_x = st.slider(label="Drag to change Turbidity (NTU)", min_value=0.0, max_value=100.0, value=8.0, step=1.0)
        elif p1 == "Water Temp":
            sim_x = st.slider(label="Drag to change Water Temp (°C)", min_value=5.0, max_value=28.0, value=16.0, step=0.5)
        else:
            sim_x = st.slider(label="Drag to change pH value", min_value=5.5, max_value=9.5, value=7.5, step=0.1)

    combined = pd.concat(
        [
            miners_ravine.assign(SiteLabel="Miners Ravine (JBDC01)"),
            dry_creek.assign(SiteLabel="Dry Creek / Saugstad (JBDC02)"),
        ],
        ignore_index=True,
    ).dropna(subset=[p1, yval])

    cov = combined[p1].cov(combined[yval])
    var = combined[p1].var()
    slope = cov / var if var != 0 else 0.0
    intercept = combined[yval].mean() - slope * combined[p1].mean()
    predicted_y = round(slope * sim_x + intercept, 2)

    sc1, sc2, sc3 = st.columns(3)
    sc1.metric(f"Simulated {p1} (Input)", f"{sim_x}")
    sc2.metric(f"Predicted {yval} (Output)", f"{predicted_y}")
    sc3.metric("Fitted Slope (Δy / Δx)", f"{slope:+.3f}")
    st.caption(f"The line is fitted to {len(combined)} field samples, so predictions are rough and will improve as more samples are added.")

    if HAS_PLOTLY:
        fig_sim = px.scatter(
            combined,
            x=p1,
            y=yval,
            color="SiteLabel",
            title=f"Simulated {yval} ({predicted_y}) at {p1} = {sim_x}",
        )
        x_line = [min(combined[p1].min(), sim_x), max(combined[p1].max(), sim_x)]
        y_line = [slope * xv + intercept for xv in x_line]
        fig_sim.add_trace(
            go.Scatter(x=x_line, y=y_line, mode="lines", name="Regression Fit", line=dict(dash="dash", color="#5F6368"))
        )
        fig_sim.add_trace(
            go.Scatter(
                x=[sim_x],
                y=[predicted_y],
                mode="markers+text",
                name="Simulated Point",
                text=[f"Simulated: ({sim_x}, {predicted_y})"],
                textposition="top center",
                marker=dict(size=14, color="#EA4335", symbol="star"),
            )
        )
        st.plotly_chart(fig_sim, use_container_width=True)
    else:
        fig_s, ax_s = plt.subplots(figsize=(7.5, 4.0))
        sns.scatterplot(data=combined, x=p1, y=yval, hue="SiteLabel", s=70, ax=ax_s)
        x_vals = [min(combined[p1].min(), sim_x), max(combined[p1].max(), sim_x)]
        ax_s.plot(x_vals, [slope * xv + intercept for xv in x_vals], "--", color="gray", label="Linear Fit")
        ax_s.scatter([sim_x], [predicted_y], color="red", s=140, zorder=5, label=f"Simulated ({sim_x}, {predicted_y})")
        ax_s.legend()
        ax_s.set_title(f"Simulated {yval} ({predicted_y}) at {p1} = {sim_x}")
        st.pyplot(fig_s)


# ===========================================================================
# TAB 10: UPLOAD YOUR OWN DATA  (visitors chart their own csv, doesn't touch our data)
# ===========================================================================
elif selected_tab == "Upload Data":
    st.header("📤 Upload Data")
    mode = st.segmented_control(
        "What do you want to do?", ["🔍 Explore a file (not saved)", "📥 Add data to the dashboard (partners)"], default="🔍 Explore a file (not saved)",
    ) or "🔍 Explore a file (not saved)"

    if mode == "🔍 Explore a file (not saved)":
        st.markdown(
            "Upload any CSV file to make your own charts. Your file is only used in your browser session. It isn't saved, "
            "and it doesn't change the DCC monitoring data in the other tabs."
        )
        st.caption(
            "Tip: if your file has a date column and columns named `DO`, `SPC`, `PH`, `Turbidity`, or `Water Temp`, "
            "the time chart will also show the healthy / watch / stressed color bands used in the rest of the dashboard."
        )

        user_file = st.file_uploader("Choose a CSV file", type="csv", key="explore_upload")

        if user_file is None:
            st.info("No file uploaded yet. Not sure how to format one? Download the example below, which uses the DCC field data layout.")
            st.download_button(
                label="⬇️ Download Example CSV",
                data=data.to_csv(index=False).encode("utf-8"),
                file_name="example_water_quality.csv",
                mime="text/csv",
            )
        else:
            udf = None
            try:
                udf = pd.read_csv(user_file)
                # the county rainfall export has '#' comment lines at the top, skip those
                if len(udf.columns) and str(udf.columns[0]).startswith("#"):
                    user_file.seek(0)
                    udf = pd.read_csv(user_file, comment="#")
            except Exception as exc:
                st.error(f"Couldn't read that file as a CSV. ({exc})")

            if udf is not None and udf.empty:
                st.warning("That file doesn't have any rows.")
            elif udf is not None:
                udf = udf.dropna(how="all")
                udf.columns = udf.columns.astype(str).str.strip()

                def try_parse_dates(series):
                    # dates like 7/26/2026, or the CDEC/USGS style ones "20000101 0000" and 202001
                    if pd.api.types.is_bool_dtype(series):
                        return pd.Series(pd.NaT, index=series.index)
                    text = series.astype(str).str.strip()
                    if pd.api.types.is_numeric_dtype(series):
                        text = series.astype("Int64").astype(str)
                        formats = ["%Y%m%d", "%Y%m"]
                    else:
                        formats = ["mixed", "%Y%m%d %H%M"]
                    best = pd.Series(pd.NaT, index=series.index)
                    for fmt in formats:
                        try:
                            parsed = pd.to_datetime(text, format=fmt, errors="coerce")
                        except (ValueError, TypeError):
                            continue
                        if parsed.notna().mean() > best.notna().mean():
                            best = parsed
                    return best

                # figure out which columns are dates / numbers / groups
                date_cols = []
                for c in udf.columns:
                    if pd.api.types.is_numeric_dtype(udf[c]) and "date" not in c.lower():
                        continue
                    if try_parse_dates(udf[c]).notna().mean() > 0.8:
                        date_cols.append(c)

                for c in udf.columns:
                    if c in date_cols or pd.api.types.is_numeric_dtype(udf[c]) or pd.api.types.is_bool_dtype(udf[c]):
                        continue
                    as_num = pd.to_numeric(udf[c], errors="coerce")
                    if as_num.notna().mean() > 0.8:
                        udf[c] = as_num

                num_cols = [
                    c for c in udf.columns
                    if pd.api.types.is_numeric_dtype(udf[c]) and not pd.api.types.is_bool_dtype(udf[c]) and c not in date_cols
                ]
                group_cols = [c for c in udf.columns if c not in num_cols and c not in date_cols and 1 < udf[c].nunique() <= 20]

                m1, m2, m3 = st.columns(3)
                m1.metric("Rows", f"{len(udf):,}")
                m2.metric("Columns", len(udf.columns))
                m3.metric("Number Columns", len(num_cols))

                with st.expander("Preview your data", expanded=False):
                    st.dataframe(udf.head(100), use_container_width=True, hide_index=True)

                if not num_cols:
                    st.warning("No number columns were found in this file, so there's nothing to chart.")
                else:
                    with st.expander("Summary statistics", expanded=False):
                        st.dataframe(udf[num_cols].describe().T.round(2), use_container_width=True)

                    chart_types = []
                    if date_cols:
                        chart_types.append("Over time")
                    if len(num_cols) >= 2:
                        chart_types.append("Compare two columns (scatter)")
                    chart_types += ["Distribution (histogram)", "Box plot"]

                    cc1, cc2 = st.columns(2)
                    with cc1:
                        chart_type = st.radio("Chart type", chart_types, horizontal=True)
                    with cc2:
                        # color by Site if there is one, otherwise the line zig zags between sites (looked awful)
                        group_options = ["(none)"] + group_cols
                        site_like = [c for c in group_cols if c.lower() in ("site", "site name", "station", "stationcode")]
                        group_by = st.selectbox(
                            "Color by (optional)",
                            group_options,
                            index=group_options.index(site_like[0]) if site_like else 0,
                        )
                    color = None if group_by == "(none)" else group_by
                    # start on DO etc if the file has it
                    std_params = [c for c in ["DO", "SPC", "PH", "Turbidity", "Water Temp"] if c in num_cols]
                    first_param = num_cols.index(std_params[0]) if std_params else 0

                    if chart_type == "Over time":
                        t1, t2 = st.columns(2)
                        with t1:
                            dcol = st.selectbox("Date column", date_cols)
                        with t2:
                            ycol = st.selectbox("Value to plot", num_cols, index=first_param)
                        plot_df = udf.copy()
                        plot_df[dcol] = try_parse_dates(plot_df[dcol])
                        plot_df = plot_df.dropna(subset=[dcol, ycol]).sort_values(dcol)
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            fig_u = px.line(plot_df, x=dcol, y=ycol, color=color, markers=len(plot_df) <= 500, title=f"{ycol} over time")
                            if ycol in THRESHOLD_ZONES:
                                for y0, y1, fill_rgba, zone_label in THRESHOLD_ZONES[ycol]["bands"]:
                                    fig_u.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                                st.caption("Color bands: 🟩 healthy, 🟨 watch, 🟥 stressed (same ranges as the rest of the dashboard).")
                            st.plotly_chart(fig_u, use_container_width=True)
                        else:
                            st.line_chart(plot_df, x=dcol, y=ycol, color=color)

                    elif chart_type == "Compare two columns (scatter)":
                        s1, s2 = st.columns(2)
                        with s1:
                            xcol = st.selectbox("X axis", num_cols, index=0)
                        with s2:
                            ycol = st.selectbox("Y axis", num_cols, index=1)
                        plot_df = udf.dropna(subset=[xcol, ycol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.scatter(plot_df, x=xcol, y=ycol, color=color, title=f"{xcol} vs. {ycol}"), use_container_width=True)
                        else:
                            st.scatter_chart(plot_df, x=xcol, y=ycol, color=color)
                        if xcol != ycol and len(plot_df) > 2:
                            r = plot_df[xcol].corr(plot_df[ycol])
                            st.info(f"Correlation between **{xcol}** and **{ycol}**: $r = {r:.2f}$ (based on {len(plot_df)} rows).")

                    elif chart_type == "Distribution (histogram)":
                        hcol = st.selectbox("Column", num_cols, index=first_param)
                        plot_df = udf.dropna(subset=[hcol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.histogram(plot_df, x=hcol, color=color, barmode="overlay", title=f"Distribution of {hcol}"), use_container_width=True)
                        else:
                            fig_h, ax_h = plt.subplots(figsize=(7.5, 4.0))
                            sns.histplot(data=plot_df, x=hcol, hue=color, ax=ax_h)
                            st.pyplot(fig_h)

                    else:
                        bcol = st.selectbox("Column", num_cols, index=first_param)
                        plot_df = udf.dropna(subset=[bcol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.box(plot_df, x=color, y=bcol, points="all", title=f"{bcol}" + (f" by {color}" if color else "")), use_container_width=True)
                        else:
                            fig_b, ax_b = plt.subplots(figsize=(7.5, 4.0))
                            sns.boxplot(data=plot_df, x=color, y=bcol, ax=ax_b)
                            st.pyplot(fig_b)

                    st.caption("To save a chart, hover over it and click the camera icon in the top-right corner.")
    else:
        # ---- partners adding data for real (saved + shown on the dashboard) ----
        st.markdown(
            "Partner groups and DCC can add monitoring data here, for a **new site** or more samples on **sites they already have**. "
            "It gets saved for good and shows up on the **📍 Monitoring Sites** tab right away "
            "(new JBDC01 / JBDC02 samples also show up on the Dry creek / Miners Ravine tabs)."
        )

        def _secret(name):
            try:
                return st.secrets.get(name)
            except Exception:   # no secrets.toml at all
                return None

        passcodes = dict(_secret("upload_passcodes") or {})
        gh_cfg = dict(_secret("github") or {}) or None
        org = st.session_state.get("upload_org")

        last = st.session_state.pop("last_upload", None)
        if last:
            if last["error"]:
                st.warning(last["error"])
            where = "committed to GitHub (permanent)" if last["saved_to"] == "github" else "saved on this server only"
            st.success(f"✅ Saved {last['rows']} row(s), {where}. Batch `{last['batch']}`. It's on the Monitoring Sites tab now.")
            for c_url in last.get("commits", []):
                st.caption(f"Commit: {c_url}")

        if not passcodes:
            st.warning("Uploading isn't set up yet: there are no organization passcodes in the app's secrets. "
                       "See **Adding partner data** in the README.")
        elif not org:
            with st.form("org_login"):
                code = st.text_input("Organization passcode", type="password",
                                     help="Each partner organization gets its own passcode from DCC.")
                go_in = st.form_submit_button("Sign in")
            if go_in:
                match = [o for o, pw in passcodes.items() if hmac.compare_digest(str(pw), code or "")]
                if match:
                    st.session_state["upload_org"] = match[0]
                    st.rerun()
                else:
                    st.error("That passcode didn't match any organization.")

        if org:
            s1, s2 = st.columns([5, 1], vertical_alignment="center")
            s1.success(f"Signed in as **{org}**")
            if s2.button("Sign out"):
                st.session_state.pop("upload_org", None)
                st.rerun()
            if not gh_cfg:
                st.warning("No GitHub token is set up, so uploads only get saved on this server. "
                           "On Streamlit Cloud they'd disappear at the next restart.")

            my_sites = sites_df[sites_df["Organization"] == org]
            st.caption("Your sites: " + (", ".join(f"`{c}` {n}" for c, n in zip(my_sites["SiteCode"], my_sites["SiteName"])) or "none yet. Any site code in your file becomes a new site."))

            template = pd.DataFrame({
                "Date": ["2026-10-18", "2026-10-18"], "Site": ["ABC01", "ABC02"], "DO": [9.1, 8.4], "SPC": [145, 210],
                "PH": [7.4, 7.6], "Turbidity": [2.1, 4.8], "Water Temp": [14.2, 15.9],
            })
            st.download_button("⬇️ Download a template CSV", template.to_csv(index=False).encode(), "monitoring_data_template.csv", "text/csv")
            st.caption("Need at least a **date** and **site code** column plus one of DO (mg/L), conductivity (µS/cm), pH, turbidity (NTU), "
                       "water temp (°C). Your column names don't have to match exactly, you can match them up below.")

            up_key = f"contrib_upload_{st.session_state.get('contrib_n', 0)}"   # new key after a save = empty uploader
            up = st.file_uploader("Your data (CSV)", type="csv", key=up_key)
            if up is not None:
                raw = None
                if getattr(up, "size", 0) > 5 * 1024 * 1024:
                    st.error("That file is over 5 MB. Split it into smaller files please.")
                else:
                    try:
                        raw = pd.read_csv(up)
                        if len(raw.columns) and str(raw.columns[0]).startswith("#"):
                            up.seek(0)
                            raw = pd.read_csv(up, comment="#")
                        raw = raw.dropna(how="all")
                        raw.columns = raw.columns.astype(str).str.strip()
                    except Exception as exc:
                        st.error(f"Couldn't read that file as a CSV. ({exc})")
                        raw = None

                if raw is not None and raw.empty:
                    st.warning("That file doesn't have any rows.")
                elif raw is not None:
                    guess = store.guess_columns(raw.columns)
                    NOT_IN = "(not in my file)"
                    nice = {"Date": "Date", "Site": "Site code", "DO": "Dissolved oxygen (mg/L)", "SPC": "Conductivity (µS/cm)",
                            "PH": "pH", "Turbidity": "Turbidity (NTU)", "Water Temp": "Water temp"}
                    with st.expander("🔗 Match your columns", expanded=not (guess["Date"] and guess["Site"])):
                        opts = [NOT_IN] + list(raw.columns)
                        mapping = {}
                        mcols = st.columns(4)
                        for i, field in enumerate(nice):
                            pick = mcols[i % 4].selectbox(nice[field], opts, index=opts.index(guess[field]) if guess[field] else 0,
                                                          key=f"map_{field}_{up_key}")
                            mapping[field] = None if pick == NOT_IN else pick
                        # header says F? then start with the switch on
                        looks_f = bool(mapping["Water Temp"]) and bool(re.search(r"\(f\)|°\s*f|\bdeg\s*f\b|fahrenheit", mapping["Water Temp"], re.I))
                        temp_f = st.toggle("My water temperatures are in °F (convert them)", value=looks_f, key=f"tf_{up_key}")

                    if not mapping["Date"] or not mapping["Site"]:
                        st.error("Pick which column is the **date** and which is the **site code** above.")
                    elif not any(mapping[p] for p in store.PARAMS):
                        st.error("Match at least one measurement column (DO, conductivity, pH, turbidity or water temp).")
                    else:
                        clean, problems, warns = store.clean_upload(raw, mapping, temp_in_f=temp_f)

                        owner = dict(zip(sites_df["SiteCode"].astype(str).str.upper(), sites_df["Organization"]))
                        codes_in = sorted(clean["Site"].unique()) if len(clean) else []
                        theirs = [c for c in codes_in if c in owner and owner[c] != org]
                        new_codes = [c for c in codes_in if c not in owner]
                        old_codes = [c for c in codes_in if owner.get(c) == org]
                        if theirs:
                            problems.append(f"Skipped site(s) {', '.join(theirs)}: they belong to another organization.")
                            clean = clean[~clean["Site"].isin(theirs)].reset_index(drop=True)
                        clean, n_have = store.drop_existing(clean, all_samples)
                        if n_have:
                            problems.append(f"{n_have} row(s) skipped: there's already data for that site on that date.")

                        u1, u2, u3 = st.columns(3)
                        u1.metric("Rows ready to save", len(clean))
                        u2.metric("Your existing sites", len(old_codes))
                        u3.metric("New sites", len(new_codes))
                        for p_ in problems:
                            st.warning(p_)
                        for w_ in warns:
                            st.info(w_)

                        new_sites = None
                        site_errs = []
                        if new_codes and len(clean):
                            st.markdown("#### New sites in this file")
                            st.caption("Fill these in so the sites can go on the map. Latitude / longitude in decimal degrees "
                                       "(Google Maps → right click the spot → click the numbers to copy them).")
                            blank = pd.DataFrame({"SiteCode": new_codes, "SiteName": [""] * len(new_codes), "Creek": [""] * len(new_codes),
                                                  "Watershed": [""] * len(new_codes), "Latitude": [None] * len(new_codes),
                                                  "Longitude": [None] * len(new_codes), "Notes": [""] * len(new_codes)})
                            new_sites = st.data_editor(
                                blank, hide_index=True, use_container_width=True, disabled=["SiteCode"], key=f"newsites_{up_key}",
                                column_config={
                                    "SiteCode": st.column_config.TextColumn("Site code"),
                                    "SiteName": st.column_config.TextColumn("Site name", required=True),
                                    "Latitude": st.column_config.NumberColumn("Latitude", format="%.6f", min_value=32.0, max_value=42.1),
                                    "Longitude": st.column_config.NumberColumn("Longitude", format="%.6f", min_value=-124.5, max_value=-114.0),
                                },
                            )
                            site_errs = store.check_new_sites(new_sites, sites_df)
                            if site_errs:
                                st.error("Before you can save:\n" + "\n".join(f"- {e_}" for e_ in site_errs))

                        if len(clean):
                            with st.expander(f"Preview ({len(clean)} rows)", expanded=False):
                                st.dataframe(clean, use_container_width=True, hide_index=True)
                            ok_public = st.checkbox("I confirm this data is accurate and OK to show publicly on the dashboard.", key=f"ok_{up_key}")
                            if st.button("💾 Save to the dashboard", type="primary", disabled=not ok_public or bool(site_errs)):
                                with st.spinner("Saving..."):
                                    res = store.save_upload(clean, new_sites if new_codes else None, org, gh_cfg)
                                res["rows"] = len(clean)
                                load_community.clear()
                                st.session_state["last_upload"] = res
                                st.session_state["contrib_n"] = st.session_state.get("contrib_n", 0) + 1
                                st.rerun()
                        else:
                            st.info("Nothing left to save from this file.")


# ===========================================================================
# TAB 11: HISTORICAL ANALYSIS (other groups data - NOT our sampling)
# ===========================================================================
elif selected_tab == "Historical Analysis":
    st.header("🕰️ Historical Analysis")
    st.caption(
        "Data from other groups that have monitored creeks around Roseville over the years. "
        "Our own JBDC01 / JBDC02 samples stay on the monitoring tabs and only show up here as ⭐ stars for comparison."
    )

    hist_dir = BASE_DIR / "Raw_data"
    SOURCES = [
        {"label": other_sources.SOURCE_CEDEN, "kind": "ceden", "folder": hist_dir / "ceden", "prefix": "dry_creek_watershed_ceden",
         "default": True, "icon": "🏛️", "short": "CEDEN (state)",
         "what": "California's water quality database (State Water Board). Mostly the state SWAMP program, stations all over the Dry Creek watershed."},
        {"label": other_sources.SOURCE_ESMR_DRY, "kind": "esmr", "folder": hist_dir / "esmr", "prefix": "roseville_wwtp_esmr",
         "default": True, "icon": "🏭", "short": "Dry Creek WWTP",
         "what": "City of Roseville wastewater plant has to monitor Dry Creek above + below its outfall (eSMR reports). ~3 km below JBDC02, weekly since 2010."},
        {"label": other_sources.SOURCE_ESMR_PG, "kind": "esmr", "folder": hist_dir / "esmr", "prefix": "roseville_wwtp_esmr",
         "default": False, "icon": "🏭", "short": "Pleasant Grove WWTP",
         "what": "Same thing for Roseville's Pleasant Grove plant, on Pleasant Grove Creek. Different watershed so it's off by default."},
        {"label": other_sources.SOURCE_USGS, "kind": "usgs", "folder": hist_dir / "usgs", "prefix": "dry_creek_usgs",
         "default": True, "icon": "🌊", "short": "USGS",
         "what": "USGS stream gauges (Dry Creek @ Vernon St 1996-2012, Miners Ravine 1978-81, a trib 1963-67) + a couple 2005 samples."},
    ]
    src_by_label = {s["label"]: s for s in SOURCES}

    live_store = st.session_state.setdefault("hist_live", {})

    def _source_data(src):
        # live download from this session wins, otherwise newest saved file
        if src["label"] in live_store:
            d, when = live_store[src["label"]]
            return d, f"Live download this session ({when})"
        path = other_sources.latest_file(src["folder"], src["prefix"])
        if path is None:
            return pd.DataFrame(columns=other_sources.UNIFIED_COLUMNS), "No saved data yet"
        d = load_history_file(src["kind"], str(path), path.stat().st_mtime)
        if src["kind"] == "esmr":
            d = d[d["Source"] == src["label"]]   # both plants are in one file
        # TODO: ask the city for the real RSW-001/002 coordinates, eSMR doesnt have them
        return d, f"Saved download, {path.name.split('_')[-1][:10]} (`{path.relative_to(BASE_DIR)}`)"

    loaded = {s["label"]: _source_data(s) for s in SOURCES}

    # source buttons + filters popover
    top_l, top_r = st.columns([5, 1], vertical_alignment="bottom")
    with top_l:
        picked = st.pills(
            "Data sources",
            [s["label"] for s in SOURCES],
            selection_mode="multi",
            default=[s["label"] for s in SOURCES if s["default"]],
            format_func=lambda lab: f"{src_by_label[lab]['icon']} {src_by_label[lab]['short']}",
        ) or []

    frames = [loaded[lab][0] for lab in picked if not loaded[lab][0].empty]
    hist = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=other_sources.UNIFIED_COLUMNS)
    hist["DataQuality"] = hist["DataQuality"].fillna("Not provided")

    dq_all = sorted(hist["DataQuality"].unique().tolist())
    dq_skip = set(ceden.DQ_NOT_MEASUREMENTS + ceden.DQ_REJECTED + ["Extensive review needed"])
    creek_all = sorted(hist["Creek"].dropna().unique().tolist())
    cur_months = sorted(set(miners_ravine["Date"].dt.month) | set(dry_creek["Date"].dt.month))
    month_names = ", ".join(pd.Timestamp(2000, m_, 1).strftime("%b") for m_ in cur_months)

    with top_r:
        with st.popover("⚙️ Filters", use_container_width=True):
            dq_pick = st.multiselect(
                "Data quality", dq_all, default=[d for d in dq_all if d not in dq_skip],
                help="CEDEN rates every record. 'Reject record' and 'MetaData' (QC records) are hidden by default, 'Extensive review needed' too. "
                "eSMR is the plant's own monitoring so it isn't rated. USGS marks data approved or provisional.",
            )
            creek_pick = st.multiselect("Creeks", creek_all, default=creek_all)
            same_season = st.toggle(f"Compare same months as our samples ({month_names})", value=True,
                                    help="Creeks run warmer with less oxygen in summer, so summer vs all-year isn't a fair fight.")
            incl_downstream = st.toggle("Include stations just below a wastewater outfall", value=False,
                                        help="eSMR RSW-002 stations. Treated wastewater is mixed in there (conductivity is way higher), so it's not normal creek water.")

    if not picked:
        st.info("Pick at least one data source above 👆")
    elif hist.empty:
        st.info("Nothing saved for those sources yet. Go to **🔎 More data → Refresh** to download it.")
    else:
        view = hist[hist["DataQuality"].isin(dq_pick) & hist["Creek"].isin(creek_pick)]
        if not incl_downstream:
            view = view[~view["StationNote"].fillna("").str.contains("downstream of the wastewater discharge")]
        view = view.dropna(subset=["Result", "SampleDate"])
        field = view[view["Parameter"].notna()]
        # st.write(view.shape, field.shape)  # debug

        params_with_data = [p for p in ceden.PARAMETERS if (field["Parameter"] == p).any()]
        short_lab = {"DO": "💨 Dissolved Oxygen", "SPC": "⚡ Conductivity", "PH": "🧪 pH", "Turbidity": "🌫️ Turbidity", "Water Temp": "🌡️ Water Temp"}
        if params_with_data:
            pcol = st.segmented_control("Parameter", params_with_data, default=params_with_data[0],
                                        format_func=lambda c: short_lab.get(c, c)) or params_with_data[0]
        else:
            pcol = None

        sub_c = field[field["Parameter"] == pcol].sort_values("SampleDate") if pcol else field.iloc[0:0]
        cmp_src = sub_c[sub_c["SampleDate"].dt.month.isin(cur_months)] if same_season else sub_c
        ours = pd.concat([miners_ravine.assign(Site="JBDC01"), dry_creek.assign(Site="JBDC02")], ignore_index=True)

        # numbers row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Historical readings", f"{len(sub_c):,}", help="for the parameter picked above")
        k2.metric("Years of history", f"{sub_c['SampleDate'].min():%Y} – {sub_c['SampleDate'].max():%Y}" if len(sub_c) else "—")
        k3.metric("Stations", sub_c["StationCode"].nunique())
        if pcol and len(cmp_src):
            hist_med = cmp_src["Result"].median()
            our_med = ours[pcol].median()
            k4.metric("Our median vs history", f"{our_med:.2f}", f"{our_med - hist_med:+.2f} vs {hist_med:.2f}", delta_color="off",
                      help="history = all selected sources" + (f", {month_names} only" if same_season else ""))
        else:
            k4.metric("Our median vs history", "—")

        t_cmp, t_trend, t_where, t_more = st.tabs(["📈 Compare", "📊 Trends", "🗺️ Where & when", "🔎 More data"])

        # ----- compare tab -----
        with t_cmp:
            if not pcol:
                st.info("None of the selected records are DO, conductivity, pH, turbidity or water temp. Try another source.")
            else:
                show_mine = st.toggle("Show our samples as ⭐", value=True)
                plot_c = sub_c.assign(Src=sub_c["Source"].map(lambda s_: src_by_label[s_]["short"]))
                fig_h = px.scatter(
                    plot_c, x="SampleDate", y="Result", color="Creek", symbol="Src",
                    hover_data=["StationName", "Source", "DataQuality"], opacity=0.55,
                )
                fig_h.update_traces(marker=dict(size=6))
                if pcol in THRESHOLD_ZONES:
                    for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                        fig_h.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                if show_mine:
                    for site_df, name, colr in [(miners_ravine, "⭐ Ours: Miners Ravine (JBDC01)", "#1A73E8"),
                                                (dry_creek, "⭐ Ours: Dry Creek (JBDC02)", "#111111")]:
                        fig_h.add_trace(go.Scatter(x=site_df["Date"], y=site_df[pcol], mode="markers", name=name,
                                                   marker=dict(size=15, symbol="star", color=colr, line=dict(width=1, color="white"))))
                fig_h.update_layout(
                    title=f"{ceden.PARAMETER_LABELS[pcol]}: every historical reading", height=470,
                    xaxis_title=None, yaxis_title=ceden.PARAMETER_LABELS[pcol],
                    legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, title=None),
                    margin=dict(l=10, r=10, t=50, b=10),
                )
                st.plotly_chart(fig_h, use_container_width=True)

                # range chart - where do our samples land vs the usual range
                def _km(lat1, lon1, lat2, lon2):
                    p = math.pi / 180
                    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
                    return 12742 * math.asin(math.sqrt(a))

                rng_rows = []
                for site_df, site, creek, s_lat, s_lon in [
                    (miners_ravine, "JBDC01", "Miners Ravine", 38.752945, -121.241526),
                    (dry_creek, "JBDC02", "Dry Creek", 38.742738, -121.284156),
                ]:
                    cr = cmp_src[cmp_src["Creek"] == creek]
                    if cr.empty:
                        continue
                    dist = pd.Series([_km(s_lat, s_lon, la, lo) if pd.notna(la) and pd.notna(lo) else 99
                                      for la, lo in zip(cr["Latitude"], cr["Longitude"])], index=cr.index, dtype=float)
                    groups = []
                    near = cr.loc[dist <= 2.0]
                    if len(near) >= 4:
                        groups.append((f"{site} vs {creek} stations within 2 km", near))
                    for s_lab, g in cr.groupby("Source"):
                        if len(g) >= 4:
                            groups.append((f"{site} vs all of {creek} · {src_by_label[s_lab]['short']}", g))
                    for lab, g in groups:
                        rng_rows.append({"label": lab, "site": site, "q25": g["Result"].quantile(.25), "med": g["Result"].median(),
                                         "q75": g["Result"].quantile(.75), "n": len(g),
                                         "years": f"{g['SampleDate'].min():%Y}–{g['SampleDate'].max():%Y}",
                                         "ours": site_df[pcol].dropna().tolist(), "our_dates": site_df.dropna(subset=[pcol])["Date"].dt.strftime("%b %d, %Y").tolist()})

                st.markdown(f"#### How do our samples stack up?")
                if not rng_rows:
                    st.caption("Not enough historical readings on Miners Ravine or Dry Creek with these filters.")
                else:
                    rr = pd.DataFrame(rng_rows)
                    fig_r = go.Figure()
                    if pcol in THRESHOLD_ZONES:
                        for x0, x1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                            fig_r.add_vrect(x0=x0, x1=x1, fillcolor=fill_rgba, line_width=0, layer="below")
                    fig_r.add_trace(go.Bar(
                        y=rr["label"], x=rr["q75"] - rr["q25"], base=rr["q25"], orientation="h",
                        marker=dict(color="rgba(95,99,104,0.35)", line=dict(color="#5F6368", width=1)),
                        name="Typical range (middle 50%)",
                        customdata=rr[["n", "years", "med"]].values,
                        hovertemplate="%{y}<br>middle 50%%: %{base:.2f} – %{x:.2f} wide<br>median %{customdata[2]:.2f} · n=%{customdata[0]} · %{customdata[1]}<extra></extra>",
                    ))
                    fig_r.add_trace(go.Scatter(y=rr["label"], x=rr["med"], mode="markers", name="Historical median",
                                               marker=dict(symbol="line-ns-open", size=22, color="#202124", line=dict(width=3))))
                    star_y, star_x, star_txt = [], [], []
                    for _, r in rr.iterrows():
                        for v, dte in zip(r["ours"], r["our_dates"]):
                            star_y.append(r["label"]); star_x.append(v); star_txt.append(f"{r['site']} {dte}: {v}")
                    fig_r.add_trace(go.Scatter(y=star_y, x=star_x, mode="markers", name="⭐ Our samples", text=star_txt, hoverinfo="text",
                                               marker=dict(symbol="star", size=15, color="#1A73E8", line=dict(width=1, color="white"))))
                    fig_r.update_layout(
                        height=110 + 48 * len(rr), barmode="overlay", xaxis_title=ceden.PARAMETER_LABELS[pcol],
                        yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.25, x=0),
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    st.plotly_chart(fig_r, use_container_width=True)
                    st.caption("Gray bar = where the middle half of the historical readings fall. Black tick = historical median. "
                               "⭐ = our samples." + (f" History limited to {month_names}." if same_season else ""))

                # same week readings as cards
                wk_rows = []
                for site_df, site, creek in [(miners_ravine, "JBDC01", "Miners Ravine"), (dry_creek, "JBDC02", "Dry Creek")]:
                    creek_all_rows = sub_c[sub_c["Creek"] == creek]
                    for _, srow in site_df.dropna(subset=[pcol]).iterrows():
                        nt = creek_all_rows[(creek_all_rows["SampleDate"] - srow["Date"]).abs() <= pd.Timedelta(days=4)]
                        for _, h in nt.iterrows():
                            wk_rows.append({"DCC site": site, "DCC date": srow["Date"], "DCC value": srow[pcol],
                                            "Other station": h["StationName"], "Source": h["Source"],
                                            "Their date": h["SampleDate"], "Their value": round(h["Result"], 2),
                                            "Difference (DCC − theirs)": round(srow[pcol] - h["Result"], 2)})
                if wk_rows:
                    st.markdown("#### Same week, same creek")
                    st.caption("Other groups' readings within 4 days of one of our samples — the closest thing to a side-by-side check.")
                    cards = st.columns(min(len(wk_rows), 4))
                    for col, w in zip(cards, wk_rows[:4]):
                        col.metric(
                            f"{w['Other station']} · {w['Their date']:%b %d}",
                            f"{w['Their value']}",
                            f"ours {w['DCC value']} ({w['DCC site']}, {w['DCC date']:%b %d})", delta_color="off", border=True,
                        )

                with st.expander("See the numbers"):
                    if rng_rows:
                        st.dataframe(pd.DataFrame(rng_rows)[["label", "n", "q25", "med", "q75", "years"]]
                                     .rename(columns={"label": "Comparison", "n": "Records", "q25": "25th pct", "med": "Median", "q75": "75th pct", "years": "Years"})
                                     .round(2), use_container_width=True, hide_index=True)
                    if wk_rows:
                        wk_df = pd.DataFrame(wk_rows)
                        wk_df["DCC date"] = wk_df["DCC date"].dt.strftime("%Y-%m-%d")
                        wk_df["Their date"] = wk_df["Their date"].dt.strftime("%Y-%m-%d")
                        st.dataframe(wk_df, use_container_width=True, hide_index=True)
                    st.caption("Other programs sampled at different spots, times of day, and how often (the Dry Creek plant did DO weekly till 2019 then monthly). "
                               "Treat this as context, not a strict before/after test.")

        # ----- trends tab -----
        with t_trend:
            if not pcol or cmp_src.empty:
                st.info("No readings to trend with these filters.")
            else:
                tr = cmp_src.copy()
                tr["Year"] = tr["SampleDate"].dt.year
                tr["Series"] = tr["Creek"] + " · " + tr["Source"].map(lambda s_: src_by_label[s_]["short"])
                all_creeks = st.toggle("Show every creek (not just Miners Ravine + Dry Creek)", value=False)
                if not all_creeks:
                    tr = tr[tr["Creek"].isin(["Miners Ravine", "Dry Creek"])]
                yearly = tr.groupby(["Series", "Year"])["Result"].agg(["median", "size"]).reset_index()
                keep = yearly.groupby("Series")["Year"].nunique()
                yearly = yearly[yearly["Series"].isin(keep[keep >= 2].index)]
                # fill missing years with NaN so plotly breaks the line instead of drawing across a 10 yr gap
                if not yearly.empty:
                    yrs = range(int(yearly["Year"].min()), int(yearly["Year"].max()) + 1)
                    yearly = (yearly.set_index(["Series", "Year"])
                              .reindex(pd.MultiIndex.from_product([yearly["Series"].unique(), yrs], names=["Series", "Year"]))
                              .reset_index())
                if yearly.empty:
                    st.caption("Not enough years of data for a trend line here.")
                else:
                    fig_t = px.line(yearly, x="Year", y="median", color="Series", markers=True,
                                    hover_data={"size": True}, labels={"median": ceden.PARAMETER_LABELS[pcol], "size": "readings"})
                    if pcol in THRESHOLD_ZONES:
                        for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                            fig_t.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                    for site_df, nm, colr in [(miners_ravine, "⭐ Ours: JBDC01", "#1A73E8"), (dry_creek, "⭐ Ours: JBDC02", "#111111")]:
                        if site_df[pcol].notna().any():
                            fig_t.add_trace(go.Scatter(x=[site_df["Date"].dt.year.max()], y=[site_df[pcol].median()], mode="markers", name=nm,
                                                       marker=dict(symbol="star", size=17, color=colr, line=dict(width=1, color="white"))))
                    fig_t.update_layout(height=460, title=f"Median {ceden.PARAMETER_LABELS[pcol]} by year" + (f" ({month_names} only)" if same_season else ""),
                                        legend=dict(orientation="h", y=-0.2, x=0, title=None), margin=dict(l=10, r=10, t=50, b=10))
                    st.plotly_chart(fig_t, use_container_width=True)
                    st.caption("Each dot is one year's median. Gaps = years nobody sampled that creek. ⭐ = median of our samples this year.")

                with st.expander("See the numbers (by period)"):
                    tr["Period"] = pd.cut(tr["Year"], [1949, 1999, 2004, 2009, 2014, 2019, 2023, 2100],
                                          labels=["Before 2000", "2000–04", "2005–09", "2010–14", "2015–19", "2020–23", "2024+"])
                    trend = tr.pivot_table(index=["Source", "Creek"], columns="Period", values="Result", aggfunc="median", observed=True).round(2)
                    counts = tr.pivot_table(index=["Source", "Creek"], columns="Period", values="Result", aggfunc="size", observed=True)
                    trend_show = trend.astype(object).where(trend.isna(), trend.astype(str) + " (n=" + counts.astype("Int64").astype(str) + ")")
                    trend_show.columns = [str(c) for c in trend_show.columns]   # categorical headers dont serialize
                    st.dataframe(trend_show.fillna("—"), use_container_width=True)

        # ----- where & when tab -----
        with t_where:
            src_colors = {other_sources.SOURCE_CEDEN: "#5F6368", other_sources.SOURCE_ESMR_DRY: "#E37400",
                          other_sources.SOURCE_ESMR_PG: "#A142F4", other_sources.SOURCE_USGS: "#188038"}
            stations = (
                view.groupby(["Source", "StationCode", "StationName", "Creek"], dropna=False)
                .agg(Records=("Result", "size"), First=("SampleDate", "min"), Last=("SampleDate", "max"),
                     Lat=("Latitude", "mean"), Lon=("Longitude", "mean"), Approx=("LocationApproximate", "max"))
                .reset_index().sort_values("Records", ascending=False)
            )
            w_map, w_heat = st.columns([1, 1])
            with w_map:
                st.markdown("**Where**")
                smap = folium.Map(location=[38.76, -121.30], zoom_start=11)
                for _, srow in stations.dropna(subset=["Lat", "Lon"]).iterrows():
                    folium.CircleMarker(
                        location=[srow["Lat"], srow["Lon"]], radius=3 + min(5, math.log10(max(srow["Records"], 1)) * 1.6),
                        color=src_colors.get(srow["Source"], "#5F6368"), fill=True, fill_opacity=0.75,
                        tooltip=f"{srow['StationName']} — {srow['Records']:,} readings, {srow['First']:%Y}–{srow['Last']:%Y}"
                        + (" (approx. location)" if srow["Approx"] else ""),
                    ).add_to(smap)
                for lat, lon, lab in [(38.752945, -121.241526, "⭐ DCC site JBDC01 Miners Ravine"), (38.742738, -121.284156, "⭐ DCC site JBDC02 Saugstad Park")]:
                    folium.Marker(location=[lat, lon], tooltip=lab, icon=folium.Icon(color="blue", icon="star")).add_to(smap)
                st_folium(smap, height=430, use_container_width=True, returned_objects=[], key="hist_station_map")
                st.caption("🔵 DCC sites · ⚪ CEDEN · 🟠 Dry Creek WWTP (approx.) · 🟣 Pleasant Grove WWTP (approx.) · 🟢 USGS. Bigger dot = more readings.")
            with w_heat:
                st.markdown("**When**")
                cov = view.copy()
                cov["Year"] = cov["SampleDate"].dt.year
                cov["Row"] = cov["Creek"] + " · " + cov["Source"].map(lambda s_: src_by_label[s_]["short"])
                ours_cov = ours.assign(Year=ours["Date"].dt.year, Row="⭐ Our sites (DCC)")
                cnt = pd.concat([cov.groupby(["Row", "Year"])["SampleDate"].nunique().rename("n").reset_index(),
                                 ours_cov.groupby(["Row", "Year"])["Date"].nunique().rename("n").reset_index()])
                y0_heat = 1995 if (cnt["Year"] >= 1995).any() else int(cnt["Year"].min())
                old_rows = cnt[cnt["Year"] < y0_heat]
                cnt = cnt[cnt["Year"] >= y0_heat]
                heat = cnt.pivot(index="Row", columns="Year", values="n")
                heat = heat.reindex(columns=range(y0_heat, int(cnt["Year"].max()) + 1))
                # log colours, otherwise a gauge with 365 days/yr makes a 6 visit year look empty
                fig_c = px.imshow(np.log10(heat + 1), aspect="auto", color_continuous_scale="Blues", zmin=0)
                fig_c.update_traces(customdata=heat.values, hovertemplate="%{y}<br>%{x}: %{customdata} days sampled<extra></extra>")
                fig_c.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False, xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_c, use_container_width=True)
                st.caption("Darker = more days sampled that year. Blank = nobody sampled."
                           + (f" (Older USGS gauge years before {y0_heat} are in the station list.)" if len(old_rows) else ""))

            with st.expander("Station list"):
                show_st = stations.drop(columns=["Lat", "Lon", "Approx"]).copy()
                show_st["First"] = show_st["First"].dt.strftime("%Y-%m-%d")
                show_st["Last"] = show_st["Last"].dt.strftime("%Y-%m-%d")
                st.dataframe(show_st, use_container_width=True, hide_index=True)

        # ----- more data tab -----
        with t_more:
            st.markdown("**Other measurements** (stream flow, nutrients, hardness, pesticides, habitat scores...)")
            other = view[view["Parameter"].isna()]
            if other.empty:
                st.caption("No other measurements with these filters.")
            else:
                counts = other.groupby(["Analyte", "Unit"]).size().sort_values(ascending=False)
                labels = [f"{a} ({u}): {n:,} records" for (a, u), n in counts.items()]
                pick = st.selectbox("Measurement", labels)
                a_sel, u_sel = counts.index[labels.index(pick)]
                o = other[(other["Analyte"] == a_sel) & (other["Unit"] == u_sel)].sort_values("SampleDate")
                if a_sel.startswith("Stream flow"):
                    figo = px.line(o, x="SampleDate", y="Result", color="StationName", title=f"{a_sel} ({u_sel})")
                    figo.update_yaxes(type="log", title="cfs (log scale)")
                else:
                    figo = px.scatter(o, x="SampleDate", y="Result", color="Creek", symbol="Source",
                                      hover_data=["StationName", "DataQuality"], title=f"{a_sel} ({u_sel})")
                figo.update_layout(legend=dict(orientation="h", y=-0.2, x=0, title=None))
                st.plotly_chart(figo, use_container_width=True)

            st.download_button("⬇️ Download these historical records (CSV)", data=view.to_csv(index=False).encode("utf-8"),
                               file_name="Roseville_Area_Historical_Records.csv", mime="text/csv")

            st.divider()
            st.markdown("**About the sources**")
            summary_rows = []
            for s in SOURCES:
                d, note = loaded[s["label"]]
                summary_rows.append({
                    "Use": "✅" if s["label"] in picked else "", "Source": s["label"], "What it is": s["what"],
                    "Records": f"{len(d):,}", "Stations": d["StationCode"].nunique() if len(d) else 0,
                    "Years": f"{d['SampleDate'].min():%Y}–{d['SampleDate'].max():%Y}" if len(d) and d["SampleDate"].notna().any() else "—",
                    "Data": note,
                })
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
            st.caption("CEDEN + eSMR are published by the State Water Resources Control Board on data.ca.gov. USGS data is from "
                       "waterservices.usgs.gov and the Water Quality Portal. eSMR has no station coordinates so those map spots are approximate.")

    # refresh goes at the bottom of More data. but it also needs to show up when nothing is loaded (first run)
    refresh_box = t_more if (picked and not hist.empty) else st.container()
    with refresh_box:
        with st.expander("🔄 Refresh a source from the internet"):
            st.caption("Downloads the newest data for this session only. To save it for everyone run the downloader scripts "
                       "(`download_roseville_ceden_history.py`, `download_esmr_usgs_history.py`) and push the new files in `Raw_data/`.")
            which = st.radio("Source", ["CEDEN", "eSMR (both Roseville plants)", "USGS"], horizontal=True)
            chosen_tables = None
            if which == "CEDEN":
                try:
                    all_tables = ceden_year_tables()
                except Exception as exc:
                    all_tables = []
                    st.error(f"Couldn't reach data.ca.gov: {exc}")
                if all_tables:
                    r1, r2 = st.columns(2)
                    with r1:
                        ds_pick = st.multiselect("CEDEN datasets", list(ceden.DATASETS.values()), default=list(ceden.DATASETS.values()))
                    with r2:
                        yr_pick = st.multiselect("Years (empty = all)", sorted({t["year"] for t in all_tables}, reverse=True), key="ceden_years")
                    chosen_tables = [t for t in all_tables if t["dataset_label"] in ds_pick and (not yr_pick or t["year"] in yr_pick)]
                    st.caption(f"{len(chosen_tables)} table(s). All years takes 1-3 min.")
            elif which.startswith("eSMR"):
                try:
                    all_tables = esmr_year_tables()
                except Exception as exc:
                    all_tables = []
                    st.error(f"Couldn't reach data.ca.gov: {exc}")
                if all_tables:
                    yr_pick = st.multiselect("Years (empty = all)", [t["year"] for t in reversed(all_tables)], key="esmr_years")
                    chosen_tables = [t for t in all_tables if not yr_pick or t["year"] in yr_pick]
                    st.caption(f"{len(chosen_tables)} yearly table(s). eSMR tables are huge, ~30-90 sec per year.")
            else:
                st.caption("USGS daily stream flow + field samples. Under a minute.")

            if st.button("📥 Download", type="primary", disabled=(which != "USGS" and not chosen_tables)):
                prog = st.progress(0.0, text="Starting download...")

                def _tick(done, total, t):
                    prog.progress(done / total, text=f"{t['name']} ({done}/{total})")

                when = pd.Timestamp.now().strftime("%b %d, %Y %I:%M %p")
                if which == "CEDEN":
                    raw, problems = ceden.harvest(chosen_tables, progress=_tick)
                    new = {other_sources.SOURCE_CEDEN: other_sources.ceden_to_unified(raw)}
                elif which.startswith("eSMR"):
                    both, problems = other_sources.harvest_esmr(chosen_tables, progress=_tick)
                    new = {lab: both[both["Source"] == lab] for lab in (other_sources.SOURCE_ESMR_DRY, other_sources.SOURCE_ESMR_PG)}
                else:
                    usgs_df, problems = other_sources.harvest_usgs()
                    new = {other_sources.SOURCE_USGS: usgs_df}
                prog.empty()
                if problems:
                    with st.expander(f"⚠️ {len(problems)} part(s) could not be downloaded", expanded=True):
                        for pr in problems:
                            st.warning(f"**{pr['table']}**: {pr['error']}")
                got = {k: v for k, v in new.items() if not v.empty}
                if got:
                    for k, v in got.items():
                        v = v.copy()
                        v["SampleDate"] = pd.to_datetime(v["SampleDate"], errors="coerce")
                        live_store[k] = (v, when)
                    st.success("Downloaded: " + ", ".join(f"{k} ({len(v):,} records)" for k, v in got.items()))
                    st.rerun()
                else:
                    st.warning("Nothing came back for that selection.")
            if live_store and st.button("Go back to the saved downloads"):
                st.session_state["hist_live"] = {}
                st.rerun()
