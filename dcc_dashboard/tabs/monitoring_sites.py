"""Monitoring Sites tab - every site incl. partner uploads (map, table, charts)"""
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import site_data_store as store
from dcc_dashboard.shared import THRESHOLD_ZONES, px


def render(ctx):
    all_samples, sites_df = ctx.all_samples, ctx.sites_df
    st.header("📍 Monitoring Sites")
    st.caption("Every site on the dashboard: our JBDC01 / JBDC02 plus any site a partner group (or DCC) added through **📤 Upload Data**.")

    ms = all_samples.copy()
    ms["Date"] = pd.to_datetime(ms["Date"], format="mixed", errors="coerce")
    ms = ms.dropna(subset=["Date"])
    info = sites_df.copy()
    info["SiteCode"] = info["SiteCode"].astype(str).str.upper()
    # data for a site that somehow isnt registered still shows up
    for c in sorted(set(ms["Site"]) - set(info["SiteCode"])):
        info.loc[len(info)] = {"SiteCode": c, "SiteName": c, "Organization": ms.loc[ms["Site"] == c, "Organization"].iloc[0]}
    name_of = dict(zip(info["SiteCode"], info["SiteName"].fillna(info["SiteCode"])))
    org_of = dict(zip(info["SiteCode"], info["Organization"]))

    def site_label(code):
        return f"{code} · {name_of.get(code, code)}"

    orgs = sorted(info["Organization"].dropna().unique())
    # pills get their own row, org names are long and were getting cut off in a column
    org_pick = st.pills("Organization", orgs, selection_mode="multi", default=orgs) or []
    codes_avail = info.loc[info["Organization"].isin(org_pick), "SiteCode"].tolist()
    site_pick = st.multiselect("Sites", codes_avail, default=codes_avail, format_func=site_label)

    sub = ms[ms["Site"].isin(site_pick)].sort_values("Date")
    sub = sub.assign(SiteLabel=sub["Site"].map(site_label))

    def health(row):
        # same rule as the overview map, but only checks what the site actually measures
        checks = []
        if pd.notna(row.get("DO")): checks.append(row["DO"] > 7)
        if pd.notna(row.get("PH")): checks.append(6.5 < row["PH"] < 8.5)
        if pd.notna(row.get("Turbidity")): checks.append(row["Turbidity"] < 10)
        if pd.notna(row.get("Water Temp")): checks.append(row["Water Temp"] < 20)
        if pd.notna(row.get("SPC")): checks.append(row["SPC"] < 200)
        if not checks:
            return "No data"
        return "Healthy" if all(checks) else "Stressed"

    if not site_pick:
        st.info("Pick at least one organization / site above.")
    else:
        latest = sub.groupby("Site").tail(1).set_index("Site")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Sites", len(site_pick))
        k2.metric("Organizations", len({org_of.get(c) for c in site_pick}))
        k3.metric("Samples", f"{len(sub):,}")
        k4.metric("Latest sample", f"{sub['Date'].max():%b %d, %Y}" if len(sub) else "—")

        m_col, t_col = st.columns([1, 1])
        with m_col:
            smap = folium.Map(location=[38.80, -121.20], zoom_start=10)
            pts = []
            for code in site_pick:
                r = info[info["SiteCode"] == code].iloc[0]
                lat, lon = pd.to_numeric(r.get("Latitude"), errors="coerce"), pd.to_numeric(r.get("Longitude"), errors="coerce")
                if pd.isna(lat) or pd.isna(lon):
                    continue
                stat = health(latest.loc[code]) if code in latest.index else "No data"
                colr = {"Healthy": "green", "Stressed": "red"}.get(stat, "gray")
                folium.CircleMarker(location=[lat, lon], radius=9, color=colr, fill=True, fill_color=colr, fill_opacity=0.85,
                                    tooltip=f"{site_label(code)} ({r['Organization']}) · latest: {stat}").add_to(smap)
                pts.append([lat, lon])
            if len(pts) > 1:
                smap.fit_bounds(pts, padding=(30, 30))
            elif pts:
                smap.location = pts[0]
            st_folium(smap, height=380, use_container_width=True, returned_objects=[], key="sites_map")
            st.caption("🟢 latest sample healthy · 🔴 something in the watch/stressed range · ⚪ no data yet")
        with t_col:
            rows = []
            for code in site_pick:
                d_ = sub[sub["Site"] == code]
                rows.append({
                    "Site": code, "Name": name_of.get(code, code), "Organization": org_of.get(code, ""),
                    "Samples": len(d_), "First": f"{d_['Date'].min():%Y-%m-%d}" if len(d_) else "—",
                    "Last": f"{d_['Date'].max():%Y-%m-%d}" if len(d_) else "—",
                    "Latest": health(latest.loc[code]) if code in latest.index else "No data",
                })
            # height grows w/ the number of sites (max = map height) so theres no wall of empty rows
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(380, 38 + 35 * len(rows)))

        if sub.empty:
            st.info("No samples yet for the selected sites.")
        else:
            have = [p for p in store.PARAMS if sub[p].notna().any()]
            nice_p = {"DO": "💨 Dissolved Oxygen", "SPC": "⚡ Conductivity", "PH": "🧪 pH", "Turbidity": "🌫️ Turbidity", "Water Temp": "🌡️ Water Temp"}
            pp = st.segmented_control("Parameter", have, default=have[0], format_func=lambda c: nice_p.get(c, c), key="sites_param") or have[0]
            spec = THRESHOLD_ZONES[pp]

            tr_tab, box_tab, last_tab = st.tabs(["📈 Over time", "📦 Site vs site", "🔎 Latest reading"])
            with tr_tab:
                fig_s = px.line(sub.dropna(subset=[pp]), x="Date", y=pp, color="SiteLabel", markers=True,
                                hover_data={"Organization": True, "SiteLabel": False})
                for y0, y1, fill_rgba, _lab in spec["bands"]:
                    fig_s.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                fig_s.update_layout(height=430, yaxis_title=f"{pp} ({spec['unit']})", xaxis_title=None,
                                    legend=dict(orientation="h", y=-0.18, x=0, title=None), margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_s, use_container_width=True)
            with box_tab:
                fig_b = px.box(sub.dropna(subset=[pp]), x="SiteLabel", y=pp, color="Organization", points="all")
                for y0, y1, fill_rgba, _lab in spec["bands"]:
                    fig_b.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                fig_b.update_layout(height=430, xaxis_title=None, yaxis_title=f"{pp} ({spec['unit']})",
                                    legend=dict(orientation="h", y=-0.25, x=0), margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_b, use_container_width=True)
                st.caption("Each box = the middle half of that site's samples, line = median, dots = every sample.")
            with last_tab:
                one = st.selectbox("Site", site_pick, format_func=site_label, key="sites_latest")
                if one in latest.index:
                    lr = latest.loc[one]
                    st.caption(f"Latest sample: {lr['Date']:%B %d, %Y} · {org_of.get(one, '')}")

                    def zone(p_, v):
                        for y0, y1, fill_rgba, _lab in THRESHOLD_ZONES[p_]["bands"]:
                            if y0 <= v <= y1:
                                return "🟢 healthy" if "52, 168, 83" in fill_rgba else ("🟡 watch" if "249, 171, 0" in fill_rgba else "🔴 stressed")
                        return "outside chart range"

                    lc = st.columns(5)
                    for col, p_ in zip(lc, store.PARAMS):
                        v = lr.get(p_)
                        if pd.notna(v):
                            col.metric(p_, f"{v:g} {THRESHOLD_ZONES[p_]['unit'] if p_ != 'PH' else ''}".strip(), zone(p_, v), delta_color="off", border=True)
                        else:
                            col.metric(p_, "—", "not measured", delta_color="off", border=True)
                else:
                    st.caption("No samples for that site yet.")

            st.download_button("⬇️ Download these sites' data (CSV)",
                               sub.drop(columns=["SiteLabel"]).assign(Date=sub["Date"].dt.strftime("%Y-%m-%d")).to_csv(index=False).encode(),
                               "monitoring_sites_data.csv", "text/csv")
