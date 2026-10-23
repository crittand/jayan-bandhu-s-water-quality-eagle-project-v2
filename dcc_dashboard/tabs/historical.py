"""Historical Analysis tab - other groups' data (CEDEN, eSMR, USGS), NOT our sampling"""
import math

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import download_esmr_usgs_history as other_sources
import download_roseville_ceden_history as ceden
from dcc_dashboard.shared import BASE_DIR, THRESHOLD_ZONES, ceden_year_tables, esmr_year_tables, go, load_history_file, px


def render(ctx):
    miners_ravine, dry_creek = ctx.miners_ravine, ctx.dry_creek
    st.header("🕰️ Historical Analysis")
    st.caption(
        "Data from other groups that have monitored creeks around Roseville over the years. "
        "Our own JBDC01 / JBDC02 samples stay on the monitoring tabs and only show up here as ⭐ stars for comparison."
    )

    hist_dir = BASE_DIR / "Raw_data"
    SOURCES = [
        {"label": other_sources.SOURCE_CEDEN, "kind": "ceden", "folder": hist_dir / "ceden", "prefix": "dry_creek_watershed_ceden",
         "default": True, "icon": "🏛️", "short": "CEDEN (state)",
         "what": "California's water quality database (State Water Board). Mostly the state SWAMP program, stations all over the Dry Creek watershed."},
        {"label": other_sources.SOURCE_ESMR_DRY, "kind": "esmr", "folder": hist_dir / "esmr", "prefix": "roseville_wwtp_esmr",
         "default": True, "icon": "🏭", "short": "Dry Creek WWTP",
         "what": "City of Roseville wastewater plant has to monitor Dry Creek above + below its outfall (eSMR reports). ~3 km below JBDC02, weekly since 2010."},
        {"label": other_sources.SOURCE_ESMR_PG, "kind": "esmr", "folder": hist_dir / "esmr", "prefix": "roseville_wwtp_esmr",
         "default": False, "icon": "🏭", "short": "Pleasant Grove WWTP",
         "what": "Same thing for Roseville's Pleasant Grove plant, on Pleasant Grove Creek. Different watershed so it's off by default."},
        {"label": other_sources.SOURCE_USGS, "kind": "usgs", "folder": hist_dir / "usgs", "prefix": "dry_creek_usgs",
         "default": True, "icon": "🌊", "short": "USGS",
         "what": "USGS stream gauges (Dry Creek @ Vernon St 1996-2012, Miners Ravine 1978-81, a trib 1963-67) + a couple 2005 samples."},
    ]
    src_by_label = {s["label"]: s for s in SOURCES}

    live_store = st.session_state.setdefault("hist_live", {})

    def _source_data(src):
        # live download from this session wins, otherwise newest saved file
        if src["label"] in live_store:
            d, when = live_store[src["label"]]
            return d, f"Live download this session ({when})"
        path = other_sources.latest_file(src["folder"], src["prefix"])
        if path is None:
            return pd.DataFrame(columns=other_sources.UNIFIED_COLUMNS), "No saved data yet"
        d = load_history_file(src["kind"], str(path), path.stat().st_mtime)
        if src["kind"] == "esmr":
            d = d[d["Source"] == src["label"]]   # both plants are in one file
        # TODO: ask the city for the real RSW-001/002 coordinates, eSMR doesnt have them
        return d, f"Saved download, {path.name.split('_')[-1][:10]} (`{path.relative_to(BASE_DIR)}`)"

    loaded = {s["label"]: _source_data(s) for s in SOURCES}

    # source buttons + filters popover
    top_l, top_r = st.columns([5, 1], vertical_alignment="bottom")
    with top_l:
        picked = st.pills(
            "Data sources",
            [s["label"] for s in SOURCES],
            selection_mode="multi",
            default=[s["label"] for s in SOURCES if s["default"]],
            format_func=lambda lab: f"{src_by_label[lab]['icon']} {src_by_label[lab]['short']}",
        ) or []

    frames = [loaded[lab][0] for lab in picked if not loaded[lab][0].empty]
    hist = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=other_sources.UNIFIED_COLUMNS)
    hist["DataQuality"] = hist["DataQuality"].fillna("Not provided")

    dq_all = sorted(hist["DataQuality"].unique().tolist())
    dq_skip = set(ceden.DQ_NOT_MEASUREMENTS + ceden.DQ_REJECTED + ["Extensive review needed"])
    creek_all = sorted(hist["Creek"].dropna().unique().tolist())
    cur_months = sorted(set(miners_ravine["Date"].dt.month) | set(dry_creek["Date"].dt.month))
    month_names = ", ".join(pd.Timestamp(2000, m_, 1).strftime("%b") for m_ in cur_months)

    with top_r:
        with st.popover("⚙️ Filters", use_container_width=True):
            dq_pick = st.multiselect(
                "Data quality", dq_all, default=[d for d in dq_all if d not in dq_skip],
                help="CEDEN rates every record. 'Reject record' and 'MetaData' (QC records) are hidden by default, 'Extensive review needed' too. "
                "eSMR is the plant's own monitoring so it isn't rated. USGS marks data approved or provisional.",
            )
            creek_pick = st.multiselect("Creeks", creek_all, default=creek_all)
            same_season = st.toggle(f"Compare same months as our samples ({month_names})", value=True,
                                    help="Creeks run warmer with less oxygen in summer, so summer vs all-year isn't a fair fight.")
            incl_downstream = st.toggle("Include stations just below a wastewater outfall", value=False,
                                        help="eSMR RSW-002 stations. Treated wastewater is mixed in there (conductivity is way higher), so it's not normal creek water.")

    if not picked:
        st.info("Pick at least one data source above 👆")
    elif hist.empty:
        st.info("Nothing saved for those sources yet. Go to **🔎 More data → Refresh** to download it.")
    else:
        view = hist[hist["DataQuality"].isin(dq_pick) & hist["Creek"].isin(creek_pick)]
        if not incl_downstream:
            view = view[~view["StationNote"].fillna("").str.contains("downstream of the wastewater discharge")]
        view = view.dropna(subset=["Result", "SampleDate"])
        field = view[view["Parameter"].notna()]
        # st.write(view.shape, field.shape)  # debug

        params_with_data = [p for p in ceden.PARAMETERS if (field["Parameter"] == p).any()]
        short_lab = {"DO": "💨 Dissolved Oxygen", "SPC": "⚡ Conductivity", "PH": "🧪 pH", "Turbidity": "🌫️ Turbidity", "Water Temp": "🌡️ Water Temp"}
        if params_with_data:
            pcol = st.segmented_control("Parameter", params_with_data, default=params_with_data[0],
                                        format_func=lambda c: short_lab.get(c, c)) or params_with_data[0]
        else:
            pcol = None

        sub_c = field[field["Parameter"] == pcol].sort_values("SampleDate") if pcol else field.iloc[0:0]
        cmp_src = sub_c[sub_c["SampleDate"].dt.month.isin(cur_months)] if same_season else sub_c
        ours = pd.concat([miners_ravine.assign(Site="JBDC01"), dry_creek.assign(Site="JBDC02")], ignore_index=True)

        # numbers row
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Historical readings", f"{len(sub_c):,}", help="for the parameter picked above")
        k2.metric("Years of history", f"{sub_c['SampleDate'].min():%Y} – {sub_c['SampleDate'].max():%Y}" if len(sub_c) else "—")
        k3.metric("Stations", sub_c["StationCode"].nunique())
        if pcol and len(cmp_src):
            hist_med = cmp_src["Result"].median()
            our_med = ours[pcol].median()
            k4.metric("Our median vs history", f"{our_med:.2f}", f"{our_med - hist_med:+.2f} vs {hist_med:.2f}", delta_color="off",
                      help="history = all selected sources" + (f", {month_names} only" if same_season else ""))
        else:
            k4.metric("Our median vs history", "—")

        t_cmp, t_trend, t_where, t_more = st.tabs(["📈 Compare", "📊 Trends", "🗺️ Where & when", "🔎 More data"])

        # ----- compare tab -----
        with t_cmp:
            if not pcol:
                st.info("None of the selected records are DO, conductivity, pH, turbidity or water temp. Try another source.")
            else:
                show_mine = st.toggle("Show our samples as ⭐", value=True)
                plot_c = sub_c.assign(Src=sub_c["Source"].map(lambda s_: src_by_label[s_]["short"]))
                fig_h = px.scatter(
                    plot_c, x="SampleDate", y="Result", color="Creek", symbol="Src",
                    hover_data=["StationName", "Source", "DataQuality"], opacity=0.55,
                )
                fig_h.update_traces(marker=dict(size=6))
                if pcol in THRESHOLD_ZONES:
                    for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                        fig_h.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                if show_mine:
                    for site_df, name, colr in [(miners_ravine, "⭐ Ours: Miners Ravine (JBDC01)", "#1A73E8"),
                                                (dry_creek, "⭐ Ours: Dry Creek (JBDC02)", "#111111")]:
                        fig_h.add_trace(go.Scatter(x=site_df["Date"], y=site_df[pcol], mode="markers", name=name,
                                                   marker=dict(size=15, symbol="star", color=colr, line=dict(width=1, color="white"))))
                fig_h.update_layout(
                    title=f"{ceden.PARAMETER_LABELS[pcol]}: every historical reading", height=470,
                    xaxis_title=None, yaxis_title=ceden.PARAMETER_LABELS[pcol],
                    legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, title=None),
                    margin=dict(l=10, r=10, t=50, b=10),
                )
                st.plotly_chart(fig_h, use_container_width=True)

                # range chart - where do our samples land vs the usual range
                def _km(lat1, lon1, lat2, lon2):
                    p = math.pi / 180
                    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
                    return 12742 * math.asin(math.sqrt(a))

                rng_rows = []
                for site_df, site, creek, s_lat, s_lon in [
                    (miners_ravine, "JBDC01", "Miners Ravine", 38.752945, -121.241526),
                    (dry_creek, "JBDC02", "Dry Creek", 38.742738, -121.284156),
                ]:
                    cr = cmp_src[cmp_src["Creek"] == creek]
                    if cr.empty:
                        continue
                    dist = pd.Series([_km(s_lat, s_lon, la, lo) if pd.notna(la) and pd.notna(lo) else 99
                                      for la, lo in zip(cr["Latitude"], cr["Longitude"])], index=cr.index, dtype=float)
                    groups = []
                    near = cr.loc[dist <= 2.0]
                    if len(near) >= 4:
                        groups.append((f"{site} vs {creek} stations within 2 km", near))
                    for s_lab, g in cr.groupby("Source"):
                        if len(g) >= 4:
                            groups.append((f"{site} vs all of {creek} · {src_by_label[s_lab]['short']}", g))
                    for lab, g in groups:
                        rng_rows.append({"label": lab, "site": site, "q25": g["Result"].quantile(.25), "med": g["Result"].median(),
                                         "q75": g["Result"].quantile(.75), "n": len(g),
                                         "years": f"{g['SampleDate'].min():%Y}–{g['SampleDate'].max():%Y}",
                                         "ours": site_df[pcol].dropna().tolist(), "our_dates": site_df.dropna(subset=[pcol])["Date"].dt.strftime("%b %d, %Y").tolist()})

                st.markdown(f"#### How do our samples stack up?")
                if not rng_rows:
                    st.caption("Not enough historical readings on Miners Ravine or Dry Creek with these filters.")
                else:
                    rr = pd.DataFrame(rng_rows)
                    fig_r = go.Figure()
                    if pcol in THRESHOLD_ZONES:
                        for x0, x1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                            fig_r.add_vrect(x0=x0, x1=x1, fillcolor=fill_rgba, line_width=0, layer="below")
                    fig_r.add_trace(go.Bar(
                        y=rr["label"], x=rr["q75"] - rr["q25"], base=rr["q25"], orientation="h",
                        marker=dict(color="rgba(95,99,104,0.35)", line=dict(color="#5F6368", width=1)),
                        name="Typical range (middle 50%)",
                        customdata=rr[["n", "years", "med"]].values,
                        hovertemplate="%{y}<br>middle 50%%: %{base:.2f} – %{x:.2f} wide<br>median %{customdata[2]:.2f} · n=%{customdata[0]} · %{customdata[1]}<extra></extra>",
                    ))
                    fig_r.add_trace(go.Scatter(y=rr["label"], x=rr["med"], mode="markers", name="Historical median",
                                               marker=dict(symbol="line-ns-open", size=22, color="#202124", line=dict(width=3))))
                    star_y, star_x, star_txt = [], [], []
                    for _, r in rr.iterrows():
                        for v, dte in zip(r["ours"], r["our_dates"]):
                            star_y.append(r["label"]); star_x.append(v); star_txt.append(f"{r['site']} {dte}: {v}")
                    fig_r.add_trace(go.Scatter(y=star_y, x=star_x, mode="markers", name="⭐ Our samples", text=star_txt, hoverinfo="text",
                                               marker=dict(symbol="star", size=15, color="#1A73E8", line=dict(width=1, color="white"))))
                    fig_r.update_layout(
                        height=110 + 48 * len(rr), barmode="overlay", xaxis_title=ceden.PARAMETER_LABELS[pcol],
                        yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.25, x=0),
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    st.plotly_chart(fig_r, use_container_width=True)
                    st.caption("Gray bar = where the middle half of the historical readings fall. Black tick = historical median. "
                               "⭐ = our samples." + (f" History limited to {month_names}." if same_season else ""))

                # same week readings as cards
                wk_rows = []
                for site_df, site, creek in [(miners_ravine, "JBDC01", "Miners Ravine"), (dry_creek, "JBDC02", "Dry Creek")]:
                    creek_all_rows = sub_c[sub_c["Creek"] == creek]
                    for _, srow in site_df.dropna(subset=[pcol]).iterrows():
                        nt = creek_all_rows[(creek_all_rows["SampleDate"] - srow["Date"]).abs() <= pd.Timedelta(days=4)]
                        for _, h in nt.iterrows():
                            wk_rows.append({"DCC site": site, "DCC date": srow["Date"], "DCC value": srow[pcol],
                                            "Other station": h["StationName"], "Source": h["Source"],
                                            "Their date": h["SampleDate"], "Their value": round(h["Result"], 2),
                                            "Difference (DCC − theirs)": round(srow[pcol] - h["Result"], 2)})
                if wk_rows:
                    st.markdown("#### Same week, same creek")
                    st.caption("Other groups' readings within 4 days of one of our samples — the closest thing to a side-by-side check.")
                    cards = st.columns(min(len(wk_rows), 4))
                    for col, w in zip(cards, wk_rows[:4]):
                        col.metric(
                            f"{w['Other station']} · {w['Their date']:%b %d}",
                            f"{w['Their value']}",
                            f"ours {w['DCC value']} ({w['DCC site']}, {w['DCC date']:%b %d})", delta_color="off", border=True,
                        )

                with st.expander("See the numbers"):
                    if rng_rows:
                        st.dataframe(pd.DataFrame(rng_rows)[["label", "n", "q25", "med", "q75", "years"]]
                                     .rename(columns={"label": "Comparison", "n": "Records", "q25": "25th pct", "med": "Median", "q75": "75th pct", "years": "Years"})
                                     .round(2), use_container_width=True, hide_index=True)
                    if wk_rows:
                        wk_df = pd.DataFrame(wk_rows)
                        wk_df["DCC date"] = wk_df["DCC date"].dt.strftime("%Y-%m-%d")
                        wk_df["Their date"] = wk_df["Their date"].dt.strftime("%Y-%m-%d")
                        st.dataframe(wk_df, use_container_width=True, hide_index=True)
                    st.caption("Other programs sampled at different spots, times of day, and how often (the Dry Creek plant did DO weekly till 2019 then monthly). "
                               "Treat this as context, not a strict before/after test.")

        # ----- trends tab -----
        with t_trend:
            if not pcol or cmp_src.empty:
                st.info("No readings to trend with these filters.")
            else:
                tr = cmp_src.copy()
                tr["Year"] = tr["SampleDate"].dt.year
                tr["Series"] = tr["Creek"] + " · " + tr["Source"].map(lambda s_: src_by_label[s_]["short"])
                all_creeks = st.toggle("Show every creek (not just Miners Ravine + Dry Creek)", value=False)
                if not all_creeks:
                    tr = tr[tr["Creek"].isin(["Miners Ravine", "Dry Creek"])]
                yearly = tr.groupby(["Series", "Year"])["Result"].agg(["median", "size"]).reset_index()
                keep = yearly.groupby("Series")["Year"].nunique()
                yearly = yearly[yearly["Series"].isin(keep[keep >= 2].index)]
                # fill missing years with NaN so plotly breaks the line instead of drawing across a 10 yr gap
                if not yearly.empty:
                    yrs = range(int(yearly["Year"].min()), int(yearly["Year"].max()) + 1)
                    yearly = (yearly.set_index(["Series", "Year"])
                              .reindex(pd.MultiIndex.from_product([yearly["Series"].unique(), yrs], names=["Series", "Year"]))
                              .reset_index())
                if yearly.empty:
                    st.caption("Not enough years of data for a trend line here.")
                else:
                    fig_t = px.line(yearly, x="Year", y="median", color="Series", markers=True,
                                    hover_data={"size": True}, labels={"median": ceden.PARAMETER_LABELS[pcol], "size": "readings"})
                    if pcol in THRESHOLD_ZONES:
                        for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[pcol]["bands"]:
                            fig_t.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                    for site_df, nm, colr in [(miners_ravine, "⭐ Ours: JBDC01", "#1A73E8"), (dry_creek, "⭐ Ours: JBDC02", "#111111")]:
                        if site_df[pcol].notna().any():
                            fig_t.add_trace(go.Scatter(x=[site_df["Date"].dt.year.max()], y=[site_df[pcol].median()], mode="markers", name=nm,
                                                       marker=dict(symbol="star", size=17, color=colr, line=dict(width=1, color="white"))))
                    fig_t.update_layout(height=460, title=f"Median {ceden.PARAMETER_LABELS[pcol]} by year" + (f" ({month_names} only)" if same_season else ""),
                                        legend=dict(orientation="h", y=-0.2, x=0, title=None), margin=dict(l=10, r=10, t=50, b=10))
                    st.plotly_chart(fig_t, use_container_width=True)
                    st.caption("Each dot is one year's median. Gaps = years nobody sampled that creek. ⭐ = median of our samples this year.")

                with st.expander("See the numbers (by period)"):
                    tr["Period"] = pd.cut(tr["Year"], [1949, 1999, 2004, 2009, 2014, 2019, 2023, 2100],
                                          labels=["Before 2000", "2000–04", "2005–09", "2010–14", "2015–19", "2020–23", "2024+"])
                    trend = tr.pivot_table(index=["Source", "Creek"], columns="Period", values="Result", aggfunc="median", observed=True).round(2)
                    counts = tr.pivot_table(index=["Source", "Creek"], columns="Period", values="Result", aggfunc="size", observed=True)
                    trend_show = trend.astype(object).where(trend.isna(), trend.astype(str) + " (n=" + counts.astype("Int64").astype(str) + ")")
                    trend_show.columns = [str(c) for c in trend_show.columns]   # categorical headers dont serialize
                    st.dataframe(trend_show.fillna("—"), use_container_width=True)

        # ----- where & when tab -----
        with t_where:
            src_colors = {other_sources.SOURCE_CEDEN: "#5F6368", other_sources.SOURCE_ESMR_DRY: "#E37400",
                          other_sources.SOURCE_ESMR_PG: "#A142F4", other_sources.SOURCE_USGS: "#188038"}
            stations = (
                view.groupby(["Source", "StationCode", "StationName", "Creek"], dropna=False)
                .agg(Records=("Result", "size"), First=("SampleDate", "min"), Last=("SampleDate", "max"),
                     Lat=("Latitude", "mean"), Lon=("Longitude", "mean"), Approx=("LocationApproximate", "max"))
                .reset_index().sort_values("Records", ascending=False)
            )
            w_map, w_heat = st.columns([1, 1])
            with w_map:
                st.markdown("**Where**")
                smap = folium.Map(location=[38.76, -121.30], zoom_start=11)
                for _, srow in stations.dropna(subset=["Lat", "Lon"]).iterrows():
                    folium.CircleMarker(
                        location=[srow["Lat"], srow["Lon"]], radius=3 + min(5, math.log10(max(srow["Records"], 1)) * 1.6),
                        color=src_colors.get(srow["Source"], "#5F6368"), fill=True, fill_opacity=0.75,
                        tooltip=f"{srow['StationName']} — {srow['Records']:,} readings, {srow['First']:%Y}–{srow['Last']:%Y}"
                        + (" (approx. location)" if srow["Approx"] else ""),
                    ).add_to(smap)
                for lat, lon, lab in [(38.752945, -121.241526, "⭐ DCC site JBDC01 Miners Ravine"), (38.742738, -121.284156, "⭐ DCC site JBDC02 Saugstad Park")]:
                    folium.Marker(location=[lat, lon], tooltip=lab, icon=folium.Icon(color="blue", icon="star")).add_to(smap)
                st_folium(smap, height=430, use_container_width=True, returned_objects=[], key="hist_station_map")
                st.caption("🔵 DCC sites · ⚪ CEDEN · 🟠 Dry Creek WWTP (approx.) · 🟣 Pleasant Grove WWTP (approx.) · 🟢 USGS. Bigger dot = more readings.")
            with w_heat:
                st.markdown("**When**")
                cov = view.copy()
                cov["Year"] = cov["SampleDate"].dt.year
                cov["Row"] = cov["Creek"] + " · " + cov["Source"].map(lambda s_: src_by_label[s_]["short"])
                ours_cov = ours.assign(Year=ours["Date"].dt.year, Row="⭐ Our sites (DCC)")
                cnt = pd.concat([cov.groupby(["Row", "Year"])["SampleDate"].nunique().rename("n").reset_index(),
                                 ours_cov.groupby(["Row", "Year"])["Date"].nunique().rename("n").reset_index()])
                y0_heat = 1995 if (cnt["Year"] >= 1995).any() else int(cnt["Year"].min())
                old_rows = cnt[cnt["Year"] < y0_heat]
                cnt = cnt[cnt["Year"] >= y0_heat]
                heat = cnt.pivot(index="Row", columns="Year", values="n")
                heat = heat.reindex(columns=range(y0_heat, int(cnt["Year"].max()) + 1))
                # log colours, otherwise a gauge with 365 days/yr makes a 6 visit year look empty
                fig_c = px.imshow(np.log10(heat + 1), aspect="auto", color_continuous_scale="Blues", zmin=0)
                fig_c.update_traces(customdata=heat.values, hovertemplate="%{y}<br>%{x}: %{customdata} days sampled<extra></extra>")
                fig_c.update_layout(height=430, margin=dict(l=10, r=10, t=10, b=10), coloraxis_showscale=False, xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_c, use_container_width=True)
                st.caption("Darker = more days sampled that year. Blank = nobody sampled."
                           + (f" (Older USGS gauge years before {y0_heat} are in the station list.)" if len(old_rows) else ""))

            with st.expander("Station list"):
                show_st = stations.drop(columns=["Lat", "Lon", "Approx"]).copy()
                show_st["First"] = show_st["First"].dt.strftime("%Y-%m-%d")
                show_st["Last"] = show_st["Last"].dt.strftime("%Y-%m-%d")
                st.dataframe(show_st, use_container_width=True, hide_index=True)

        # ----- more data tab -----
        with t_more:
            st.markdown("**Other measurements** (stream flow, nutrients, hardness, pesticides, habitat scores...)")
            other = view[view["Parameter"].isna()]
            if other.empty:
                st.caption("No other measurements with these filters.")
            else:
                counts = other.groupby(["Analyte", "Unit"]).size().sort_values(ascending=False)
                labels = [f"{a} ({u}): {n:,} records" for (a, u), n in counts.items()]
                pick = st.selectbox("Measurement", labels)
                a_sel, u_sel = counts.index[labels.index(pick)]
                o = other[(other["Analyte"] == a_sel) & (other["Unit"] == u_sel)].sort_values("SampleDate")
                if a_sel.startswith("Stream flow"):
                    figo = px.line(o, x="SampleDate", y="Result", color="StationName", title=f"{a_sel} ({u_sel})")
                    figo.update_yaxes(type="log", title="cfs (log scale)")
                else:
                    figo = px.scatter(o, x="SampleDate", y="Result", color="Creek", symbol="Source",
                                      hover_data=["StationName", "DataQuality"], title=f"{a_sel} ({u_sel})")
                figo.update_layout(legend=dict(orientation="h", y=-0.2, x=0, title=None))
                st.plotly_chart(figo, use_container_width=True)

            st.download_button("⬇️ Download these historical records (CSV)", data=view.to_csv(index=False).encode("utf-8"),
                               file_name="Roseville_Area_Historical_Records.csv", mime="text/csv")

            st.divider()
            st.markdown("**About the sources**")
            summary_rows = []
            for s in SOURCES:
                d, note = loaded[s["label"]]
                summary_rows.append({
                    "Use": "✅" if s["label"] in picked else "", "Source": s["label"], "What it is": s["what"],
                    "Records": f"{len(d):,}", "Stations": d["StationCode"].nunique() if len(d) else 0,
                    "Years": f"{d['SampleDate'].min():%Y}–{d['SampleDate'].max():%Y}" if len(d) and d["SampleDate"].notna().any() else "—",
                    "Data": note,
                })
            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
            st.caption("CEDEN + eSMR are published by the State Water Resources Control Board on data.ca.gov. USGS data is from "
                       "waterservices.usgs.gov and the Water Quality Portal. eSMR has no station coordinates so those map spots are approximate.")

    # refresh goes at the bottom of More data. but it also needs to show up when nothing is loaded (first run)
    refresh_box = t_more if (picked and not hist.empty) else st.container()
    with refresh_box:
        with st.expander("🔄 Refresh a source from the internet"):
            st.caption("Downloads the newest data for this session only. To save it for everyone run the downloader scripts "
                       "(`download_roseville_ceden_history.py`, `download_esmr_usgs_history.py`) and push the new files in `Raw_data/`.")
            which = st.radio("Source", ["CEDEN", "eSMR (both Roseville plants)", "USGS"], horizontal=True)
            chosen_tables = None
            if which == "CEDEN":
                try:
                    all_tables = ceden_year_tables()
                except Exception as exc:
                    all_tables = []
                    st.error(f"Couldn't reach data.ca.gov: {exc}")
                if all_tables:
                    r1, r2 = st.columns(2)
                    with r1:
                        ds_pick = st.multiselect("CEDEN datasets", list(ceden.DATASETS.values()), default=list(ceden.DATASETS.values()))
                    with r2:
                        yr_pick = st.multiselect("Years (empty = all)", sorted({t["year"] for t in all_tables}, reverse=True), key="ceden_years")
                    chosen_tables = [t for t in all_tables if t["dataset_label"] in ds_pick and (not yr_pick or t["year"] in yr_pick)]
                    st.caption(f"{len(chosen_tables)} table(s). All years takes 1-3 min.")
            elif which.startswith("eSMR"):
                try:
                    all_tables = esmr_year_tables()
                except Exception as exc:
                    all_tables = []
                    st.error(f"Couldn't reach data.ca.gov: {exc}")
                if all_tables:
                    yr_pick = st.multiselect("Years (empty = all)", [t["year"] for t in reversed(all_tables)], key="esmr_years")
                    chosen_tables = [t for t in all_tables if not yr_pick or t["year"] in yr_pick]
                    st.caption(f"{len(chosen_tables)} yearly table(s). eSMR tables are huge, ~30-90 sec per year.")
            else:
                st.caption("USGS daily stream flow + field samples. Under a minute.")

            if st.button("📥 Download", type="primary", disabled=(which != "USGS" and not chosen_tables)):
                prog = st.progress(0.0, text="Starting download...")

                def _tick(done, total, t):
                    prog.progress(done / total, text=f"{t['name']} ({done}/{total})")

                when = pd.Timestamp.now().strftime("%b %d, %Y %I:%M %p")
                if which == "CEDEN":
                    raw, problems = ceden.harvest(chosen_tables, progress=_tick)
                    new = {other_sources.SOURCE_CEDEN: other_sources.ceden_to_unified(raw)}
                elif which.startswith("eSMR"):
                    both, problems = other_sources.harvest_esmr(chosen_tables, progress=_tick)
                    new = {lab: both[both["Source"] == lab] for lab in (other_sources.SOURCE_ESMR_DRY, other_sources.SOURCE_ESMR_PG)}
                else:
                    usgs_df, problems = other_sources.harvest_usgs()
                    new = {other_sources.SOURCE_USGS: usgs_df}
                prog.empty()
                if problems:
                    with st.expander(f"⚠️ {len(problems)} part(s) could not be downloaded", expanded=True):
                        for pr in problems:
                            st.warning(f"**{pr['table']}**: {pr['error']}")
                got = {k: v for k, v in new.items() if not v.empty}
                if got:
                    for k, v in got.items():
                        v = v.copy()
                        v["SampleDate"] = pd.to_datetime(v["SampleDate"], errors="coerce")
                        live_store[k] = (v, when)
                    st.success("Downloaded: " + ", ".join(f"{k} ({len(v):,} records)" for k, v in got.items()))
                    st.rerun()
                else:
                    st.warning("Nothing came back for that selection.")
            if live_store and st.button("Go back to the saved downloads"):
                st.session_state["hist_live"] = {}
                st.rerun()
