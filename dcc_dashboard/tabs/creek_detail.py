"""Dry creek / Miners Ravine tabs - same page, different site (ctx.tab_key decides which)"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import seaborn as sns
import streamlit as st

from dcc_dashboard.shared import HAS_PLOTLY, build_plotly_threshold_chart, safe_space


def render(ctx):
    miners_ravine, dry_creek = ctx.miners_ravine, ctx.dry_creek
    is_dry = ctx.tab_key == "dry_creek"
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
