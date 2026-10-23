"""eDNA results tab - BMI metabarcoding + Jonah Ventures invasive qPCR"""
import streamlit as st

from dcc_dashboard.shared import safe_space


def render(ctx):
    qpcr = ctx.qpcr
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
