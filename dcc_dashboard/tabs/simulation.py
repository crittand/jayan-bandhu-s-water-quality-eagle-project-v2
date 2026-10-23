"""Simulation tab - what-if sliders"""
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

from dcc_dashboard.shared import HAS_PLOTLY, go, px


def render(ctx):
    miners_ravine, dry_creek = ctx.miners_ravine, ctx.dry_creek
    st.header("🔬 Interactive 'What-If' Creek Simulation")
    st.markdown(
        "**How It Works:** What happens to **Dissolved Oxygen (`DO`)** if summer **Water Temperature** rises to 24 °C? "
        "Use the controls in the **left sidebar** to pick an input variable, drag the slider, and see the predicted impact "
        "based on a linear regression fitted to the **Miners Ravine (`JBDC01`)** and **Dry Creek (`JBDC02`)** measurements!"
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
    st.caption(f"The line is fitted to {len(combined)} field samples, so predictions are rough and will improve as more samples are added.")

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
