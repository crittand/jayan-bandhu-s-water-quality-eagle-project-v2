"""Dry Creek Water Quality Monitoring - Dry Creek Conservancy (DCC)

this file just wires things together. the actual pages live in dcc_dashboard/tabs/ (one file per tab),
shared helpers in dcc_dashboard/shared.py, data loading in dcc_dashboard/data.py

    streamlit run waterquality.py
"""
import streamlit as st

st.set_page_config(
    page_title="Dry Creek Water Quality Monitoring | Dry Creek Conservancy",
    page_icon="💧",
    layout="wide",
)

from dcc_dashboard import banner, sidebar, tabs   # noqa: E402  (set_page_config has to go first)
from dcc_dashboard.data import load_all  # noqa: E402

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

# --- page layout ---
st.title("💧 Dry Creek Water Quality Monitoring")
st.caption(
    "A **Dry Creek Conservancy (DCC)** dashboard for staff, volunteers, and funding sponsors — "
    "Monthly **Physiochemical Monitoring** (equipment loaned from **Sierra Streams Institute**) & **eDNA** "
    "(**CALeDNA Lab at UCSC / eDNA Explorer** BMI Metabarcoding + **Jonah Ventures** Invasive Species qPCR)"
)

banner.show()     # salmon event QR box, hides itself after the event
selected = sidebar.show()

ctx = load_all()
ctx.tab_key = selected       # whats being shown right now (dry_creek / miners_ravine share a page)
tabs.render(selected, ctx)
