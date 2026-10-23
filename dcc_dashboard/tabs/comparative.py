"""Comparative analysis tab - Miners Ravine vs Dry Creek on one chart"""
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import seaborn as sns
import streamlit as st



def render(ctx):
    miners_ravine, dry_creek = ctx.miners_ravine, ctx.dry_creek
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
