"""PDF & Data Download tab - pdf report from a typed prompt + csv / CEDEN-style exports"""
import streamlit as st

from dcc_dashboard.shared import convert_samples_to_ceden2, pdf_download


def render(ctx):
    data, miners_ravine, dry_creek = ctx.data, ctx.miners_ravine, ctx.dry_creek
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
