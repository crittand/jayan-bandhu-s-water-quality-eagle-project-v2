"""Correlation analysis tab - scatter/regression between 2 parameters"""
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st



def render(ctx):
    miners_ravine, dry_creek = ctx.miners_ravine, ctx.dry_creek
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
