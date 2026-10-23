"""stuff more than one tab uses: imports that can fail, paths, thresholds, chart/pdf/export helpers.
no streamlit calls run at import time in here (only function defs) so its safe to import from anywhere."""
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # before pyplot gets imported anywhere
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
import seaborn as sns
import streamlit as st

import download_roseville_ceden_history as ceden
import download_esmr_usgs_history as other_sources

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    px = go = None   # so `from shared import px` still works, tabs check HAS_PLOTLY
    HAS_PLOTLY = False

# repo root (this file lives in dcc_dashboard/)
BASE_DIR = Path(__file__).resolve().parent.parent


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
