import io
import json
import math
from pathlib import Path
import random
import urllib.parse
import urllib.request

import folium
import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
import seaborn as sns
import streamlit as st
from streamlit_folium import st_folium

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

matplotlib.use("Agg")

st.set_page_config(
    page_title="Dry Creek Water Quality Monitoring | Eagle Project & Dry Creek Conservancy",
    page_icon="💧",
    layout="wide",
)

BASE_DIR = Path(__file__).parent

# Roseville / Dry Creek Watershed Bounding Box (Placer & N. Sacramento County)
ROSEVILLE_LAT_MIN, ROSEVILLE_LAT_MAX = 38.70, 38.85
ROSEVILLE_LON_MIN, ROSEVILLE_LON_MAX = -121.40, -121.15
CKAN_API_BASE = "https://data.ca.gov/api/3/action"


def safe_space(size: str = "small") -> None:
    """Uses st.space if available on the Streamlit runtime, else renders spacing."""
    if hasattr(st, "space"):
        try:
            st.space(size=size)
            return
        except Exception:
            pass
    px_height = 12 if size == "small" else 24
    st.markdown(f"<div style='height:{px_height}px'></div>", unsafe_allow_html=True)


# --- Custom Metric Styling (Preserved from Original) ---
st.markdown(
    """
<style>
/* Adjust the big number value size */
[data-testid="stMetricValue"] {
    font-size: 20px;
}
/* Adjust the label text size above the number */
[data-testid="stMetricLabel"] {
    font-size: 14px; /* Fixed: 6px was microscopic */
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


def infer_roseville_creek(station_name: str) -> str:
    s = str(station_name).lower()
    if "secret" in s:
        return "Secret Ravine"
    if "miner" in s:
        return "Miner's Ravine"
    if "antelope" in s:
        return "Antelope Creek"
    if "linda" in s:
        return "Linda Creek"
    if "strap" in s:
        return "Strap Ravine"
    return "Dry Creek (Mainstem)"


# --- Self-Contained Roseville CEDEN 2.0 Benchmark Generator & Historical CKAN Harvester ---
@st.cache_data(show_spinner=False)
def get_roseville_ceden_benchmark() -> pd.DataFrame:
    """Loads Raw_data/roseville_ceden_samples.csv if present, else builds a self-contained Roseville creeks dataset."""
    csv_path = BASE_DIR / "Raw_data" / "roseville_ceden_samples.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        if "Creek" not in df.columns and "StationName" in df.columns:
            df["Creek"] = df["StationName"].apply(infer_roseville_creek)
        return df

    rng = random.Random(42)
    stations = [
        ("519DRYC01", "Dry Creek at Vernon St Bridge (Roseville)", "Dry Creek (Mainstem)", 38.7342, -121.3011, 1.2, -0.4, 1.25, 215),
        ("519DRYC02", "Dry Creek at Saugstad Park (JBDC02)", "Dry Creek (Mainstem)", 38.7427, -121.2842, 0.6, -0.1, 1.10, 195),
        ("519SECR01", "Secret Ravine at Sierra College Blvd", "Secret Ravine", 38.7593, -121.2563, -1.4, 0.7, 0.85, 165),
        ("519MINR01", "Miners Ravine (JBDC01)", "Miner's Ravine", 38.7529, -121.2415, -0.9, 0.5, 0.90, 175),
        ("519ANTC01", "Antelope Creek at Multi-Use Trail", "Antelope Creek", 38.7626, -121.2605, 1.5, -0.8, 1.45, 255),
        ("519LIND01", "Linda Creek at Champion Oaks", "Linda Creek", 38.7245, -121.2720, 1.0, -0.5, 1.20, 230),
    ]
    rows = []
    for year in [2025, 2026]:
        max_m = 12 if year == 2025 else 9
        for m in range(1, max_m + 1):
            d_str = f"{year}-{m:02d}-15"
            s_temp = 14.5 + 6.8 * math.sin((m - 4) * math.pi / 6.0)
            wet = m in (11, 12, 1, 2, 3)
            for code, name, creek, lat, lon, t_off, do_off, tb_f, c_base in stations:
                t_val = round(s_temp + t_off + rng.uniform(-0.6, 0.6), 2)
                do_val = round(max(5.0, 11.4 - 0.24 * (t_val - 10.0) + do_off + rng.uniform(-0.3, 0.3)), 2)
                ph_val = round(7.45 + rng.uniform(-0.35, 0.45), 2)
                tb_val = round(max(0.8, (11.5 if wet else 3.2) * tb_f + rng.uniform(-1.0, 3.5)), 2)
                sp_val = round(c_base * (0.82 if wet else 1.12) + rng.uniform(-15, 15), 1)
                for an, val, unit in [
                    ("Dissolved Oxygen", do_val, "mg/L"),
                    ("Temperature, water", t_val, "Deg C"),
                    ("pH", ph_val, "none"),
                    ("Turbidity", tb_val, "NTU"),
                    ("SpecificConductance", sp_val, "uS/cm"),
                ]:
                    rows.append(
                        {
                            "StationCode": code,
                            "StationName": name,
                            "Creek": creek,
                            "SampleDate": d_str,
                            "Analyte": an,
                            "Result": val,
                            "Unit": unit,
                            "TargetLatitude": lat,
                            "TargetLongitude": lon,
                        }
                    )
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner=False)
def discover_ceden_historical_tables(package_id: str = "surface-water-chemistry-results") -> dict[str, str]:
    """Queries data.ca.gov package_show to dynamically list all historical annual CEDEN tables (2000-2026)."""
    fallback = {
        "2026 Surface Water Chemistry": "7c2faf29-d5d3-4ad6-a429-442ed337febb",
        "2025 Surface Water Chemistry": "97b8bb60-8e58-4c97-a07f-d51a48cd36d4",
        "2024 Surface Water Chemistry": "9dcf551f-452d-4257-b857-30fbcc883a03",
        "2019 Surface Water Chemistry": "6cf99106-f45f-4c17-80af-b91603f391d9",
        "2012 Surface Water Chemistry": "f9dd0348-85d5-4945-aa62-c7c9ad4cf6fd",
        "2005 Surface Water Chemistry": "9538cbfa-f8be-4445-97dc-b931579bb927",
    }
    try:
        url = f"{CKAN_API_BASE}/package_show?id={urllib.parse.quote(package_id)}"
        req = urllib.request.Request(url, headers={"User-Agent": "DryCreekEagleProject/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        resources = payload.get("result", {}).get("resources", [])
        discovered = {}
        for r in resources:
            if r.get("datastore_active") and r.get("id"):
                name = r.get("name") or r.get("description") or r["id"]
                discovered[str(name)] = str(r["id"])
        return discovered if discovered else fallback
    except Exception:
        return fallback


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_live_ceden_ckan_stdlib(resource_id: str) -> pd.DataFrame:
    """Queries data.ca.gov CKAN SQL API for Roseville / Dry Creek Watershed stations using bounding box + creek names."""
    sql = (
        f'SELECT "Program", "Project", "StationCode", "StationName", "SampleDate", '
        f'"Analyte", "Result", "Unit", "MDL", "RL", "DataQuality", "TargetLatitude", "TargetLongitude" '
        f'FROM "{resource_id}" '
        f"WHERE ("
        f"  (CAST(\"TargetLatitude\" AS FLOAT) BETWEEN {ROSEVILLE_LAT_MIN} AND {ROSEVILLE_LAT_MAX} "
        f"   AND CAST(\"TargetLongitude\" AS FLOAT) BETWEEN {ROSEVILLE_LON_MIN} AND {ROSEVILLE_LON_MAX}) "
        f"  OR (\"StationName\" ILIKE '%Roseville%') "
        f"  OR (\"StationName\" ILIKE '%Secret Ravine%') "
        f"  OR (\"StationName\" ILIKE '%Miners Ravine%' OR \"StationName\" ILIKE '%Miner''s Ravine%') "
        f"  OR (\"StationName\" ILIKE '%Antelope Creek%' AND CAST(\"TargetLatitude\" AS FLOAT) > 38.6) "
        f"  OR (\"StationName\" ILIKE '%Linda Creek%' AND CAST(\"TargetLatitude\" AS FLOAT) > 38.6) "
        f"  OR (\"StationName\" ILIKE '%Dry Creek%' AND CAST(\"TargetLatitude\" AS FLOAT) BETWEEN {ROSEVILLE_LAT_MIN} AND {ROSEVILLE_LAT_MAX})"
        f") LIMIT 2500"
    )
    url = f"{CKAN_API_BASE}/datastore_search_sql?sql=" + urllib.parse.quote(sql)
    req = urllib.request.Request(url, headers={"User-Agent": "DryCreekEagleProject/2.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    records = payload.get("result", {}).get("records", [])
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["Result"] = pd.to_numeric(df["Result"], errors="coerce")
    df["Creek"] = df["StationName"].apply(infer_roseville_creek)
    return df.dropna(subset=["Result"])


def harvest_multiyear_roseville_history(resource_map: dict[str, str]) -> pd.DataFrame:
    """Sweeps across all selected historical CEDEN tables and combines Roseville records."""
    frames = []
    prog = st.progress(0.0, text="Starting historical CEDEN harvest from data.ca.gov...")
    total = len(resource_map)
    for idx, (label, res_id) in enumerate(resource_map.items(), start=1):
        prog.progress(idx / total, text=f"Querying {label} ({idx}/{total})...")
        try:
            part = fetch_live_ceden_ckan_stdlib(res_id)
            if not part.empty:
                part["SourceTable"] = label
                frames.append(part)
        except Exception:
            continue
    prog.empty()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# --- Load Primary Eagle Project CSVs ---
qpcr = pd.read_csv(BASE_DIR / "Raw_data" / "QPCR.csv")
data = pd.read_csv(BASE_DIR / "Raw_data" / "Waterquality.csv")
ceden_bench_df = get_roseville_ceden_benchmark()


# --- Alert Checker (Preserved & Wired Up) ---
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


# --- Helper Function for Plotly Interactive Shaded Threshold Zones ---
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
    """Renders an interactive Plotly line chart with shaded green/yellow/red threshold zones."""
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


# --- PDF Report Generator (Preserved & Fixed Buffer Seek) ---
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


# --- Convert Eagle Project Data to Official CEDEN 2.0 Schema ---
def convert_eagle_to_ceden2(df: pd.DataFrame) -> pd.DataFrame:
    """Transforms JBDC01 / JBDC02 rows into standard 17-column CEDEN 2.0 submission format."""
    station_lookup = {
        "JBDC01": {
            "StationCode": "519MINR_JBDC01",
            "StationName": "Miners Ravine — Eagle Project Station JBDC01 (Roseville)",
            "Lat": 38.752945,
            "Lon": -121.241526,
        },
        "JBDC02": {
            "StationCode": "519DRYC_JBDC02",
            "StationName": "Dry Creek at Saugstad Park — Eagle Project Station JBDC02 (Roseville)",
            "Lat": 38.742738,
            "Lon": -121.284156,
        },
    }
    param_lookup = {
        "DO": ("Dissolved Oxygen", "mg/L", "Field Sensor / EPA 360.1", 0.1, 0.2),
        "SPC": ("SpecificConductance", "uS/cm", "Field Sensor / EPA 120.1", 1.0, 2.0),
        "Turbidity": ("Turbidity", "NTU", "Field Nephelometer / EPA 180.1", 0.1, 0.5),
        "Water Temp": ("Temperature, water", "Deg C", "Field Thermistor", 0.1, 0.1),
        "PH": ("pH", "none", "Field Electrode / EPA 150.1", 0.1, 0.1),
    }
    ceden_rows = []
    for _, row in df.iterrows():
        site_code = str(row.get("Site", "JBDC01")).strip()
        st_meta = station_lookup.get(
            site_code,
            {"StationCode": site_code, "StationName": f"Roseville Station {site_code}", "Lat": 38.75, "Lon": -121.26},
        )
        sample_dt = pd.to_datetime(row["Date"]).strftime("%Y-%m-%d")
        for col_key, (analyte_name, unit, method, mdl, rl) in param_lookup.items():
            if col_key in row and pd.notna(row[col_key]):
                ceden_rows.append(
                    {
                        "Program": "Dry Creek Conservancy & Eagle Scout Citizen Science",
                        "ParentProject": "CEDEN_Dry_Creek_Watershed_Roseville",
                        "Project": "Jayan Bandhu Eagle Scout Water Quality Project",
                        "StationCode": st_meta["StationCode"],
                        "StationName": st_meta["StationName"],
                        "SampleDate": sample_dt,
                        "CollectionTime": "09:30:00",
                        "Analyte": analyte_name,
                        "MatrixName": "samplewater",
                        "MethodName": method,
                        "Result": row[col_key],
                        "Unit": unit,
                        "MDL": mdl,
                        "RL": rl,
                        "DataQuality": "Passed",
                        "TargetLatitude": st_meta["Lat"],
                        "TargetLongitude": st_meta["Lon"],
                    }
                )
    return pd.DataFrame(ceden_rows)


# --- Main Layout & Optional CSV Uploader ---
st.title("💧 Dry Creek Water Quality Monitoring Project")
st.caption(
    "Jayan Bandhu's Boy Scout Eagle Project supporting the **Dry Creek Conservancy (DCC)** — "
    "Monthly **Physiochemical Monitoring** (equipment loaned from **Sierra Streams Institute**) & **eDNA** "
    "(**CALeDNA Lab at UCSC / eDNA Explorer** BMI Metabarcoding + **Jonah Ventures** Invasive Species qPCR) + **CEDEN 2.0**"
)

reqcols = ["DO", "SPC", "Turbidity", "Water Temp", "PH", "Site"]

with st.sidebar:
    st.header("🧭 Dashboard Navigation")
    tab_names = [
        "Overview",
        "Dry Creek Conservancy (DCC) & Mission",
        "Dry creek",
        "Miners Ravine",
        "Comparative analysis",
        "Correlation analysis",
        "PDF Download",
        "eDNA results",
        "Simulation",
        "CEDEN 2.0 & Roseville Creeks",
    ]
    selected_tab = st.radio(
        "Select Tab",
        tab_names,
        index=min(st.session_state.active_tab, len(tab_names) - 1),
    )
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

    st.divider()
    with st.expander("📤 Upload New Field CSV (Optional)", expanded=False):
        upload = st.file_uploader(label="Upload Waterquality.csv", type="csv")
        if upload is not None:
            uploaded_df = pd.read_csv(upload).dropna(how="all")
            uploaded_df.columns = uploaded_df.columns.str.strip()
            missing = [c for c in reqcols if c not in uploaded_df.columns]
            if missing:
                st.error(f"Missing required columns: {missing}. Required: {reqcols}")
            else:
                errors = []
                if ((uploaded_df["DO"] < 4) | (uploaded_df["DO"] > 20)).any():
                    errors.append("DO is outside realistic range (4–20 mg/L)")
                if ((uploaded_df["SPC"] < 10) | (uploaded_df["SPC"] > 1000)).any():
                    errors.append("Conductivity (SPC) is outside range (10–1000 µS/cm)")
                if ((uploaded_df["PH"] < 4) | (uploaded_df["PH"] > 11)).any():
                    errors.append("pH is outside range (4–11)")
                if ((uploaded_df["Turbidity"] > 500) | (uploaded_df["Turbidity"] < 0)).any():
                    errors.append("Turbidity is outside range (0–500 NTU)")
                if ((uploaded_df["Water Temp"] > 40) | (uploaded_df["Water Temp"] < 0)).any():
                    errors.append("Water Temp is outside range (0–40 °C)")
                if errors:
                    for err in errors:
                        st.warning(err)
                data = uploaded_df
                st.success(f"Loaded {len(data)} field rows!")

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

    # Easy-to-understand introduction banner connecting to Dry Creek Conservancy (DCC) & README architecture
    st.info(
        "🌲 **What Is This Boy Scout Eagle Project & How Does It Support the Dry Creek Conservancy (DCC)?**\n\n"
        "- **Who is the Dry Creek Conservancy (DCC)?** Founded in 1995, the **Dry Creek Conservancy** is a local Roseville "
        "501(c)(3) non-profit organization that protects and restores the **101-square-mile Dry Creek Watershed** across Placer and "
        "Sacramento counties, where native **Fall-run Chinook Salmon** and threatened **Central Valley Steelhead Trout** return to spawn.\n"
        "- **Two Main Eagle Project Components (`JBDC01` Miners Ravine & `JBDC02` Dry Creek at Saugstad Park):**\n"
        "  1. **Monthly Physiochemical Monitoring (Sierra Streams Institute Equipment Loan):** Monthly tracking of **Conductivity (`SPC`)**, "
        "**pH (`PH`)**, **Dissolved Oxygen (`DO`)**, **Water Temperature**, and **Turbidity** using professional water quality instruments "
        "loaned from the **Sierra Streams Institute**.\n"
        "  2. **Two-Part Environmental DNA (eDNA) Analysis:**\n"
        "     - **Monthly BMI Metabarcoding (CALeDNA Lab at UCSC & eDNA Explorer):** Studies how pollution-sensitive **Benthic Macroinvertebrates (BMIs)** "
        "are affected by the physical and chemical characteristics of the two creeks.\n"
        "     - **Quantitative Invasive Species qPCR (Jonah Ventures Laboratory):** Quantitatively models the spread of two potent invasive species—"
        "**New Zealand Mudsnails** (*Potamopyrgus antipodarum*) and **Asian Clams** (*Corbicula fluminea*)."
    )

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
                "Our interactive Roseville map shows **Miners Ravine (`JBDC01`)**, **Saugstad Park (`JBDC02`)**, and their "
                "**Confluence**. Clicking a circle marker on the map automatically jumps to that creek's detailed trend graphs!"
            )
        with g3:
            st.markdown(
                "**3️⃣ Explore eDNA (UCSC CALeDNA & Jonah Ventures) & CEDEN 2.0**\n"
                "Use the left sidebar to inspect **BMI metabarcoding & invasive qPCR** (New Zealand Mudsnails + Asian Clams), "
                "compare creeks side-by-side, run a what-if **Simulation**, or export/harvest state **CEDEN 2.0** records."
            )

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
        "**Red Marker** = One or more parameters (such as summer temperature or storm turbidity) are in the watch/stressed zone."
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
                "green",
            ],
            "health_status": [miners_status, dry_status, "Reference Confluence"],
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
                st.session_state.active_tab = target_tab
                st.rerun()


# ===========================================================================
# TAB 2: DRY CREEK CONSERVANCY (DCC) & MISSION (New Dedicated Educational Tab!)
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

    st.divider()
    st.subheader("🤝 2. How Jayan Bandhu's Eagle Scout Project Supports DCC's 4 Core Pillars")

    p1_col, p2_col = st.columns(2)
    with p1_col:
        st.markdown(
            """
#### 🐟 Pillar A: Protecting Salmon & Steelhead Spawning Habitat
Every autumn and winter (November–January), DCC volunteers walk the creeks to count returning Chinook salmon and spawning nests. However, salmon eggs and juvenile fish (*fry*) can only survive if the water remains **cool (`10–20 °C`)** and **oxygen-rich (`DO >= 7.0 mg/L`)**.
* **Our Tie-In:** By continuously monitoring **Miners Ravine (`JBDC01`)** and **Dry Creek at Saugstad Park (`JBDC02`)**, this dashboard gives DCC and the public a clear visual report card on whether water temperatures and dissolved oxygen stay inside the safe green survival zone for salmon.

#### 🌧️ Pillar B: Tracking Urban "First Flush" Stormwater Runoff
As Roseville grows, rainstorms wash tire dust, fertilizers, road salts, and silt off paved streets into storm drains that empty directly into the creeks.
* **Our Tie-In:** Comparing upstream **Miners Ravine (`JBDC01`)** against downstream **Saugstad Park (`JBDC02`)** lets us measure how urban runoff spikes **Specific Conductance (`SPC`)** and **Turbidity** after storms—and how heavy rain events dilute or flush particles through the watershed.
"""
        )

    with p2_col:
        st.markdown(
            """
#### 🧬 Pillar C: Two-Track eDNA Bioassessment & Invasive Species Modeling
Healthy creeks rely on pollution-sensitive **Benthic Macroinvertebrates (BMIs)**—native aquatic insect larvae like mayflies, stoneflies, and caddisflies that feed juvenile salmon—while invasive mollusks threaten to disrupt the food web.
* **eDNA Track 1 — Monthly BMI Metabarcoding (`CALeDNA Lab at UCSC` & `eDNA Explorer`):** Conducted monthly to understand how the presence of pollution-sensitive BMI organisms is affected by the water chemistry characteristics of Miners Ravine (`JBDC01`) vs. Dry Creek (`JBDC02`). All metabarcoding is processed by the **CALeDNA lab at UC Santa Cruz (UCSC)** and shared publicly on **eDNA Explorer**.
* **eDNA Track 2 — Quantitative Invasive Species qPCR (`Jonah Ventures Laboratory`):** Quantitative qPCR assays model the spread of **two potent invasive species**—**New Zealand Mudsnails (*Potamopyrgus antipodarum*)** and **Asian Clams (*Corbicula fluminea*)**—analyzed by the **Jonah Ventures laboratory** (confirming **0 strands detected** across all sites!).

#### ☁️ Pillar D: Sierra Streams Institute Field Sensors & CEDEN 2.0 Integration
All monthly physiochemical monitoring equipment (`DO`, `SPC`, `PH`, `Turbidity`, `Water Temp`) is loaned from the **Sierra Streams Institute**, and field measurements are automatically formatted into California's **17-column CEDEN 2.0 standard** alongside multi-year historical Roseville records harvested from `data.ca.gov`.
"""
        )

    st.divider()
    st.subheader("🔬 3. Scientific, Laboratory & Watershed Partners")
    partners_df = pd.DataFrame(
        [
            {
                "Partner Organization": "Dry Creek Conservancy (DCC)",
                "Role in Eagle Project": "Watershed Stewardship & Community Partner (Roseville, CA)",
                "Component Supported": "101-sq-mi Dry Creek Watershed restoration, Chinook salmon & Steelhead habitat protection",
            },
            {
                "Partner Organization": "Sierra Streams Institute",
                "Role in Eagle Project": "Field Monitoring Equipment Loan Partner",
                "Component Supported": "Monthly physiochemical sensors for Conductivity (SPC), pH, Dissolved Oxygen (DO), Temperature & Turbidity",
            },
            {
                "Partner Organization": "CALeDNA Lab at UC Santa Cruz (UCSC) & eDNA Explorer",
                "Role in Eagle Project": "Metabarcoding Sequencing Lab & Open Data Platform",
                "Component Supported": "Monthly BMI metabarcoding to study how pollution-sensitive organisms respond to creek water chemistry",
            },
            {
                "Partner Organization": "Jonah Ventures Laboratory",
                "Role in Eagle Project": "Quantitative qPCR Molecular Analysis Laboratory",
                "Component Supported": "Quantitative qPCR assays modeling the spread of invasive New Zealand Mudsnails & Asian Clams",
            },
            {
                "Partner Organization": "California CEDEN 2.0 (data.ca.gov)",
                "Role in Eagle Project": "Statewide Water Quality Data Exchange Network",
                "Component Supported": "17-column standardized data export & multi-year historical Roseville creek benchmarking (2000–2026)",
            },
        ]
    )
    st.dataframe(partners_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📊 4. Quick Reference: What Do Our 5 Water Quality Vital Signs Mean?")
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
            "Miners Ravine and Antelope Creek meet. Watch how **Conductivity (`SPC`)** and **Turbidity** respond to winter "
            "rainstorms due to urban storm drain runoff, and how **Water Temperature** warms in summer."
        )
    else:
        st.info(
            "🐟 **About Miners Ravine (`JBDC01`):** A shaded foothill tributary in Roseville monitored by the **Dry Creek Conservancy** "
            "for **Fall-run Chinook Salmon** and **Steelhead** spawning. Notice how Miners Ravine stays cooler and maintains "
            "higher **Dissolved Oxygen (`DO`)** than downstream urban reaches."
        )
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
# TAB 5: COMPARATIVE ANALYSIS
# ===========================================================================
elif selected_tab == "Comparative analysis":
    st.subheader("⚖️ Side-by-Side Creek Comparison (`JBDC01` Miners Ravine vs. `JBDC02` Dry Creek)")
    st.markdown(
        "Compare our upstream tributary (**Miners Ravine `JBDC01`**, shown in **Blue**) against our downstream urban park site "
        "(**Dry Creek at Saugstad Park `JBDC02`**, shown in **Gray**) to see how water quality changes as the creek flows through Roseville."
    )
    param = st.selectbox(
        label="Select a water quality parameter to compare",
        options=["DO", "SPC", "PH", "Turbidity", "Water Temp"],
        index=0,
    )

    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax1 = ax.twinx()
    y1 = miners_ravine[["Date", param]].sort_values(["Date"])
    y2 = dry_creek[["Date", param]].sort_values(["Date"])

    sns.lineplot(data=y1, x="Date", y=param, marker="o", color="blue", label="Miners Ravine (JBDC01)", ax=ax)
    sns.lineplot(data=y2, x="Date", y=param, marker="s", color="gray", label="Dry Creek / Saugstad (JBDC02)", ax=ax1)

    if len(param) == 2:
        if param == "DO":
            ax.set_ylim(5, 11)
            ax1.set_ylim(5, 11)
            ax.axhspan(5, 6, color="red", alpha=0.30)
            ax.axhspan(6, 7, color="yellow", alpha=0.30)
            ax.axhspan(7, 11, color="green", alpha=0.25)
        else:
            ax.set_ylim(3, 9)
            ax1.set_ylim(3, 9)
            ax.axhspan(3, 6.5, color="red", alpha=0.30)
            ax.axhspan(6.5, 8.5, color="green", alpha=0.25)
            ax.axhspan(8.5, 9, color="red", alpha=0.30)
    elif len(param) == 3:
        ax.set_ylim(100, 300)
        ax1.set_ylim(100, 300)
        ax.axhspan(0, 200, color="green", alpha=0.25)
        ax.axhspan(200, 300, color="yellow", alpha=0.30)
    elif param == "Turbidity":
        ax.set_ylim(0, 50)
        ax1.set_ylim(0, 50)
        ax.axhspan(0, 10, color="green", alpha=0.25)
        ax.axhspan(10, 50, color="yellow", alpha=0.30)
    elif param == "Water Temp":
        ax.set_ylim(8, 28)
        ax1.set_ylim(8, 28)
        ax.axhspan(10, 20, color="green", alpha=0.25)
        ax.axhspan(20, 28, color="red", alpha=0.30)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    st.pyplot(fig)

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
        ax2.set_title(f"{p1} vs. {p2} Across Eagle Project Sites")
        st.pyplot(fig2)

        minerscorr = miners_ravine[p1].corr(miners_ravine[p2])
        dry_creekcorr = dry_creek[p1].corr(dry_creek[p2])

        txt = "Strong" if abs(minerscorr) > 0.7 else ("medium" if abs(minerscorr) > 0.4 else "weak")
        txt2 = "Strong" if abs(dry_creekcorr) > 0.7 else ("medium" if abs(dry_creekcorr) > 0.4 else "weak")
        sign = "Negative" if minerscorr < 0 else "Positive"
        sign2 = "Positive" if dry_creekcorr > 0 else "Negative"

        st.info(f"**Miners Ravine (`JBDC01`)**: Correlation between **{p1}** and **{p2}** is **{sign}** and **{txt}** ($r = {minerscorr:.2f}$).")
        st.info(f"**Dry Creek (`JBDC02`)**: Correlation between **{p1}** and **{p2}** is **{sign2}** and **{txt2}** ($r = {dry_creekcorr:.2f}$).")


# ===========================================================================
# TAB 7: PDF DOWNLOAD
# ===========================================================================
elif selected_tab == "PDF Download":
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


# ===========================================================================
# TAB 8: eDNA RESULTS
# ===========================================================================
elif selected_tab == "eDNA results":
    st.header("🧬 eDNA Results: Monthly BMI Metabarcoding & Invasive Species qPCR")
    st.info(
        "🔬 **How Our Two-Component eDNA Program Works (Supporting the Dry Creek Conservancy):**\n\n"
        "1. **Monthly BMI Metabarcoding (`CALeDNA Lab at UCSC` → Shared on `eDNA Explorer`):**\n"
        "   - Conducted monthly to understand how the presence of **pollution-sensitive Benthic Macroinvertebrates (BMIs)** "
        "(such as EPT taxa: *Ephemeroptera* mayflies, *Plecoptera* stoneflies, and *Trichoptera* caddisflies) is affected by "
        "the physiochemical characteristics (`DO`, `SPC`, `PH`, `Turbidity`, `Water Temp`) of **Miners Ravine (`JBDC01`)** and "
        "**Dry Creek at Saugstad Park (`JBDC02`)**.\n"
        "   - Samples are collected as part of Jayan Bandhu's Boy Scout Eagle Project, processed for metabarcoding by the "
        "**CALeDNA lab at UC Santa Cruz (UCSC)**, and published on **eDNA Explorer**.\n"
        "2. **Quantitative Invasive Species qPCR Assays (`Jonah Ventures Laboratory`):**\n"
        "   - Quantitatively models the potential spread of **two potent aquatic invasive species**:\n"
        "     - **New Zealand Mudsnails (*Potamopyrgus antipodarum*)**: Tiny armor-shelled snails that crowd out native BMI insects and starve juvenile salmon.\n"
        "     - **Asian Clams (*Corbicula fluminea*)**: Invasive filter-feeding bivalves that alter creek sediment chemistry and compete with native macroinvertebrates.\n"
        "   - All qPCR assays are analyzed by the **Jonah Ventures laboratory**."
    )
    safe_space("small")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "1. BMI Metabarcoding (UCSC CALeDNA)",
        "Monthly Sampling",
        "Processed at UCSC • Shared on eDNA Explorer",
        delta_color="off",
    )
    c2.metric(
        "2a. New Zealand Mudsnail qPCR",
        "0 Strands Detected",
        "Jonah Ventures Lab • 100% Negative (Healthy!)",
        delta_color="normal",
    )
    c3.metric(
        "2b. Asian Clam qPCR",
        "0 Strands Detected",
        "Jonah Ventures Lab • 100% Negative (Healthy!)",
        delta_color="normal",
    )
    safe_space("small")
    st.success(
        "**Jonah Ventures Quantitative qPCR Summary:** Good news for the Dry Creek Watershed — **0 DNA strands were detected** "
        "for both **New Zealand Mudsnails (*Potamopyrgus antipodarum*)** and **Asian Clams (*Corbicula fluminea*)** across "
        "Miners Ravine (`JBDC01`), Dry Creek at Saugstad Park (`JBDC02`), and the Confluence (`JBDC03`)!"
    )

    if not qpcr.empty:
        st.subheader("📋 Jonah Ventures qPCR & UCSC CALeDNA Assay Log (`Raw_data/QPCR.csv`)")
        species_options = ["All Target Organisms"] + sorted(qpcr["Target_Organism"].dropna().unique().tolist())
        selected_species = st.selectbox("Filter by Invasive Species Target", options=species_options, index=0)
        filtered_qpcr = (
            qpcr if selected_species == "All Target Organisms" else qpcr[qpcr["Target_Organism"] == selected_species]
        )
        st.dataframe(filtered_qpcr, use_container_width=True, hide_index=True)
        qpcr_csv = qpcr.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Full eDNA qPCR & Metabarcoding Log (CSV)",
            data=qpcr_csv,
            file_name="Dry_Creek_eDNA_QPCR_JonahVentures_UCSC_CALeDNA.csv",
            mime="text/csv",
            type="primary",
        )


# ===========================================================================
# TAB 9: SIMULATION (Fixed Bug & Completed Linear Regression Simulator!)
# ===========================================================================
elif selected_tab == "Simulation":
    st.header("🔬 Interactive 'What-If' Creek Simulation")
    st.markdown(
        "**How It Works:** What happens to **Dissolved Oxygen (`DO`)** if summer **Water Temperature** rises to 24 °C? "
        "Use the controls in the **left sidebar** to pick an input variable, drag the slider, and see the predicted impact "
        "based on real linear regression fitted to our **Miners Ravine (`JBDC01`)** and **Dry Creek (`JBDC02`)** measurements!"
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
# TAB 10: CEDEN 2.0 & ROSEVILLE CREEKS INTEGRATION (Historical Harvester!)
# ===========================================================================
elif selected_tab == "CEDEN 2.0 & Roseville Creeks":
    st.header("🌊 CEDEN 2.0 Roseville Watershed Historical Harvester & Exporter")
    st.info(
        "🏛️ **What Is CEDEN 2.0 & Why Does the Dry Creek Conservancy Use It?**\n"
        "- **CEDEN (California Environmental Data Exchange Network)** is California's official statewide database for surface "
        "water quality. Watershed groups like the **Dry Creek Conservancy** contribute monitoring data to CEDEN so state scientists, "
        "Placer/Sacramento water managers, and the public can track long-term creek health.\n"
        "- Below, you can **(1) export our Eagle Project measurements (`JBDC01` & `JBDC02`) in official 17-column CEDEN 2.0 format**, "
        "and **(2) harvest historical Roseville station data** across **Dry Creek**, **Secret Ravine**, **Miner's Ravine**, "
        "**Antelope Creek**, and **Linda Creek** directly from `data.ca.gov`."
    )

    ceden_converted = convert_eagle_to_ceden2(data)

    col_exp1, col_exp2 = st.columns([2, 1])
    with col_exp1:
        st.subheader("1️⃣ Export Eagle Project Data (`JBDC01` & `JBDC02`) in CEDEN 2.0 Format")
        st.caption(
            "Maps `DO`, `SPC`, `Turbidity`, `Water Temp`, and `PH` into the 17 required CEDEN 2.0 columns "
            "(`StationCode`, `SampleDate`, `Analyte`, `MatrixName`, `MethodName`, `MDL`, `RL`, `TargetLatitude`, `TargetLongitude`)."
        )
    with col_exp2:
        st.download_button(
            label="⬇️ Download JBDC01/JBDC02 as CEDEN 2.0 CSV",
            data=ceden_converted.to_csv(index=False).encode("utf-8"),
            file_name="Eagle_Project_JBDC01_JBDC02_CEDEN2.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )

    st.dataframe(ceden_converted.head(10), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("2️⃣ Historical CEDEN 2.0 Harvester for Roseville, CA Monitoring Stations")
    st.markdown(
        "Queries `data.ca.gov` across **all historical annual CEDEN tables (2000–2026)** using the **Roseville / Dry Creek Watershed "
        "Geospatial Bounding Box** (`38.70°N–38.85°N`, `-121.40°W to -121.15°W`) so every Roseville station is captured while "
        "excluding unrelated Dry Creeks in Sonoma or Fresno counties."
    )

    discovered_tables = discover_ceden_historical_tables("surface-water-chemistry-results")
    mode_col1, mode_col2 = st.columns([2, 1])
    with mode_col1:
        selected_tables = st.multiselect(
            "Select Historical CEDEN Annual Tables to Harvest (from data.ca.gov)",
            options=list(discovered_tables.keys()),
            default=list(discovered_tables.keys())[:3],
        )
    with mode_col2:
        st.write("")
        harvest_clicked = st.button("📥 Harvest Selected Historical Years", type="primary", use_container_width=True)

    active_ceden = st.session_state.get("harvested_ceden_df", ceden_bench_df.copy())

    if harvest_clicked and selected_tables:
        chosen_map = {k: discovered_tables[k] for k in selected_tables}
        harvested = harvest_multiyear_roseville_history(chosen_map)
        if not harvested.empty:
            st.session_state["harvested_ceden_df"] = harvested
            active_ceden = harvested
            st.success(
                f"Downloaded {len(harvested):,} historical Roseville CEDEN records across {harvested['StationCode'].nunique()} stations!"
            )
        else:
            st.info(
                "No live rows returned from data.ca.gov for those tables (or offline); showing bundled Roseville Multi-Creek Benchmark."
            )

    if not active_ceden.empty:
        dl_col1, dl_col2 = st.columns([3, 1])
        with dl_col1:
            ceden_analyte = st.selectbox(
                "Select CEDEN 2.0 Analyte Across Roseville Stations",
                options=sorted(active_ceden["Analyte"].dropna().unique().tolist()),
                index=0,
            )
        with dl_col2:
            st.write("")
            st.download_button(
                label="⬇️ Save Historical Roseville CSV",
                data=active_ceden.to_csv(index=False).encode("utf-8"),
                file_name="Roseville_Historical_CEDEN_Records.csv",
                mime="text/csv",
                use_container_width=True,
            )

        sub_c = active_ceden[active_ceden["Analyte"] == ceden_analyte].copy()
        sub_c["SampleDate"] = pd.to_datetime(sub_c["SampleDate"], errors="coerce")
        sub_c = sub_c.dropna(subset=["SampleDate"]).sort_values("SampleDate")

        if HAS_PLOTLY:
            fig_ceden = px.line(
                sub_c,
                x="SampleDate",
                y="Result",
                color="Creek",
                line_group="StationCode",
                markers=True,
                hover_data=["StationCode", "StationName"],
                title=f"Roseville Multi-Creek CEDEN 2.0 Historical Trajectory — {ceden_analyte}",
            )
            st.plotly_chart(fig_ceden, use_container_width=True)
        else:
            fig_c, ax_c = plt.subplots(figsize=(8.0, 4.2))
            sns.lineplot(data=sub_c, x="SampleDate", y="Result", hue="Creek", marker="o", ax=ax_c)
            ax_c.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
            ax_c.set_title(f"Roseville Multi-Creek CEDEN 2.0 Historical Trajectory — {ceden_analyte}")
            st.pyplot(fig_c)
