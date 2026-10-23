"""DCC & Mission tab - who DCC is, the watershed map + how this project fits in"""
import pandas as pd
import streamlit as st

from dcc_dashboard.shared import BASE_DIR


def render(ctx):
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
