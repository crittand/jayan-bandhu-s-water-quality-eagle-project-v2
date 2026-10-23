"""Overview tab - KPI cards, alerts, photos, site map (click a marker -> that creek's tab)"""
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from dcc_dashboard.shared import BASE_DIR, safe_space, send_alerts


def render(ctx):
    data, qpcr, miners_ravine, dry_creek = ctx.data, ctx.qpcr, ctx.miners_ravine, ctx.dry_creek
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
            "Tab": ["miners_ravine", "dry_creek", "dry_creek"],   # tab keys (see tabs/__init__.py)
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
            target_tab = match.iloc[0]["Tab"]
            if ctx.tab_key != target_tab:
                st.session_state.pending_tab = target_tab
                st.rerun()
