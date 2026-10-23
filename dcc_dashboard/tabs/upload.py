"""Upload Data tab - explore any csv (not saved) + partner uploads (saved, passcode)"""
import hmac
import re

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

import site_data_store as store
from dcc_dashboard.shared import HAS_PLOTLY, THRESHOLD_ZONES, px
from dcc_dashboard.data import load_community


def render(ctx):
    data, all_samples, sites_df = ctx.data, ctx.all_samples, ctx.sites_df
    st.header("📤 Upload Data")
    mode = st.segmented_control(
        "What do you want to do?", ["🔍 Explore a file (not saved)", "📥 Add data to the dashboard (partners)"], default="🔍 Explore a file (not saved)",
    ) or "🔍 Explore a file (not saved)"

    if mode == "🔍 Explore a file (not saved)":
        st.markdown(
            "Upload any CSV file to make your own charts. Your file is only used in your browser session. It isn't saved, "
            "and it doesn't change the DCC monitoring data in the other tabs."
        )
        st.caption(
            "Tip: if your file has a date column and columns named `DO`, `SPC`, `PH`, `Turbidity`, or `Water Temp`, "
            "the time chart will also show the healthy / watch / stressed color bands used in the rest of the dashboard."
        )

        user_file = st.file_uploader("Choose a CSV file", type="csv", key="explore_upload")

        if user_file is None:
            st.info("No file uploaded yet. Not sure how to format one? Download the example below, which uses the DCC field data layout.")
            st.download_button(
                label="⬇️ Download Example CSV",
                data=data.to_csv(index=False).encode("utf-8"),
                file_name="example_water_quality.csv",
                mime="text/csv",
            )
        else:
            udf = None
            try:
                udf = pd.read_csv(user_file)
                # the county rainfall export has '#' comment lines at the top, skip those
                if len(udf.columns) and str(udf.columns[0]).startswith("#"):
                    user_file.seek(0)
                    udf = pd.read_csv(user_file, comment="#")
            except Exception as exc:
                st.error(f"Couldn't read that file as a CSV. ({exc})")

            if udf is not None and udf.empty:
                st.warning("That file doesn't have any rows.")
            elif udf is not None:
                udf = udf.dropna(how="all")
                udf.columns = udf.columns.astype(str).str.strip()

                def try_parse_dates(series):
                    # dates like 7/26/2026, or the CDEC/USGS style ones "20000101 0000" and 202001
                    if pd.api.types.is_bool_dtype(series):
                        return pd.Series(pd.NaT, index=series.index)
                    text = series.astype(str).str.strip()
                    if pd.api.types.is_numeric_dtype(series):
                        text = series.astype("Int64").astype(str)
                        formats = ["%Y%m%d", "%Y%m"]
                    else:
                        formats = ["mixed", "%Y%m%d %H%M"]
                    best = pd.Series(pd.NaT, index=series.index)
                    for fmt in formats:
                        try:
                            parsed = pd.to_datetime(text, format=fmt, errors="coerce")
                        except (ValueError, TypeError):
                            continue
                        if parsed.notna().mean() > best.notna().mean():
                            best = parsed
                    return best

                # figure out which columns are dates / numbers / groups
                date_cols = []
                for c in udf.columns:
                    if pd.api.types.is_numeric_dtype(udf[c]) and "date" not in c.lower():
                        continue
                    if try_parse_dates(udf[c]).notna().mean() > 0.8:
                        date_cols.append(c)

                for c in udf.columns:
                    if c in date_cols or pd.api.types.is_numeric_dtype(udf[c]) or pd.api.types.is_bool_dtype(udf[c]):
                        continue
                    as_num = pd.to_numeric(udf[c], errors="coerce")
                    if as_num.notna().mean() > 0.8:
                        udf[c] = as_num

                num_cols = [
                    c for c in udf.columns
                    if pd.api.types.is_numeric_dtype(udf[c]) and not pd.api.types.is_bool_dtype(udf[c]) and c not in date_cols
                ]
                group_cols = [c for c in udf.columns if c not in num_cols and c not in date_cols and 1 < udf[c].nunique() <= 20]

                m1, m2, m3 = st.columns(3)
                m1.metric("Rows", f"{len(udf):,}")
                m2.metric("Columns", len(udf.columns))
                m3.metric("Number Columns", len(num_cols))

                with st.expander("Preview your data", expanded=False):
                    st.dataframe(udf.head(100), use_container_width=True, hide_index=True)

                if not num_cols:
                    st.warning("No number columns were found in this file, so there's nothing to chart.")
                else:
                    with st.expander("Summary statistics", expanded=False):
                        st.dataframe(udf[num_cols].describe().T.round(2), use_container_width=True)

                    chart_types = []
                    if date_cols:
                        chart_types.append("Over time")
                    if len(num_cols) >= 2:
                        chart_types.append("Compare two columns (scatter)")
                    chart_types += ["Distribution (histogram)", "Box plot"]

                    cc1, cc2 = st.columns(2)
                    with cc1:
                        chart_type = st.radio("Chart type", chart_types, horizontal=True)
                    with cc2:
                        # color by Site if there is one, otherwise the line zig zags between sites (looked awful)
                        group_options = ["(none)"] + group_cols
                        site_like = [c for c in group_cols if c.lower() in ("site", "site name", "station", "stationcode")]
                        group_by = st.selectbox(
                            "Color by (optional)",
                            group_options,
                            index=group_options.index(site_like[0]) if site_like else 0,
                        )
                    color = None if group_by == "(none)" else group_by
                    # start on DO etc if the file has it
                    std_params = [c for c in ["DO", "SPC", "PH", "Turbidity", "Water Temp"] if c in num_cols]
                    first_param = num_cols.index(std_params[0]) if std_params else 0

                    if chart_type == "Over time":
                        t1, t2 = st.columns(2)
                        with t1:
                            dcol = st.selectbox("Date column", date_cols)
                        with t2:
                            ycol = st.selectbox("Value to plot", num_cols, index=first_param)
                        plot_df = udf.copy()
                        plot_df[dcol] = try_parse_dates(plot_df[dcol])
                        plot_df = plot_df.dropna(subset=[dcol, ycol]).sort_values(dcol)
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            fig_u = px.line(plot_df, x=dcol, y=ycol, color=color, markers=len(plot_df) <= 500, title=f"{ycol} over time")
                            if ycol in THRESHOLD_ZONES:
                                for y0, y1, fill_rgba, zone_label in THRESHOLD_ZONES[ycol]["bands"]:
                                    fig_u.add_hrect(y0=y0, y1=y1, fillcolor=fill_rgba, line_width=0, layer="below")
                                st.caption("Color bands: 🟩 healthy, 🟨 watch, 🟥 stressed (same ranges as the rest of the dashboard).")
                            st.plotly_chart(fig_u, use_container_width=True)
                        else:
                            st.line_chart(plot_df, x=dcol, y=ycol, color=color)

                    elif chart_type == "Compare two columns (scatter)":
                        s1, s2 = st.columns(2)
                        with s1:
                            xcol = st.selectbox("X axis", num_cols, index=0)
                        with s2:
                            ycol = st.selectbox("Y axis", num_cols, index=1)
                        plot_df = udf.dropna(subset=[xcol, ycol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.scatter(plot_df, x=xcol, y=ycol, color=color, title=f"{xcol} vs. {ycol}"), use_container_width=True)
                        else:
                            st.scatter_chart(plot_df, x=xcol, y=ycol, color=color)
                        if xcol != ycol and len(plot_df) > 2:
                            r = plot_df[xcol].corr(plot_df[ycol])
                            st.info(f"Correlation between **{xcol}** and **{ycol}**: $r = {r:.2f}$ (based on {len(plot_df)} rows).")

                    elif chart_type == "Distribution (histogram)":
                        hcol = st.selectbox("Column", num_cols, index=first_param)
                        plot_df = udf.dropna(subset=[hcol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.histogram(plot_df, x=hcol, color=color, barmode="overlay", title=f"Distribution of {hcol}"), use_container_width=True)
                        else:
                            fig_h, ax_h = plt.subplots(figsize=(7.5, 4.0))
                            sns.histplot(data=plot_df, x=hcol, hue=color, ax=ax_h)
                            st.pyplot(fig_h)

                    else:
                        bcol = st.selectbox("Column", num_cols, index=first_param)
                        plot_df = udf.dropna(subset=[bcol]).copy()
                        if color:
                            plot_df[color] = plot_df[color].astype(str)
                        if HAS_PLOTLY:
                            st.plotly_chart(px.box(plot_df, x=color, y=bcol, points="all", title=f"{bcol}" + (f" by {color}" if color else "")), use_container_width=True)
                        else:
                            fig_b, ax_b = plt.subplots(figsize=(7.5, 4.0))
                            sns.boxplot(data=plot_df, x=color, y=bcol, ax=ax_b)
                            st.pyplot(fig_b)

                    st.caption("To save a chart, hover over it and click the camera icon in the top-right corner.")
    else:
        # ---- partners adding data for real (saved + shown on the dashboard) ----
        st.markdown(
            "Partner groups and DCC can add monitoring data here, for a **new site** or more samples on **sites they already have**. "
            "It gets saved for good and shows up on the **📍 Monitoring Sites** tab right away "
            "(new JBDC01 / JBDC02 samples also show up on the Dry creek / Miners Ravine tabs)."
        )

        def _secret(name):
            try:
                return st.secrets.get(name)
            except Exception:   # no secrets.toml at all
                return None

        passcodes = dict(_secret("upload_passcodes") or {})
        gh_cfg = dict(_secret("github") or {}) or None
        org = st.session_state.get("upload_org")

        last = st.session_state.pop("last_upload", None)
        if last:
            if last["error"]:
                st.warning(last["error"])
            where = "committed to GitHub (permanent)" if last["saved_to"] == "github" else "saved on this server only"
            st.success(f"✅ Saved {last['rows']} row(s), {where}. Batch `{last['batch']}`. It's on the Monitoring Sites tab now.")
            for c_url in last.get("commits", []):
                st.caption(f"Commit: {c_url}")

        if not passcodes:
            st.warning("Uploading isn't set up yet: there are no organization passcodes in the app's secrets. "
                       "See **Adding partner data** in the README.")
        elif not org:
            with st.form("org_login"):
                code = st.text_input("Organization passcode", type="password",
                                     help="Each partner organization gets its own passcode from DCC.")
                go_in = st.form_submit_button("Sign in")
            if go_in:
                match = [o for o, pw in passcodes.items() if hmac.compare_digest(str(pw), code or "")]
                if match:
                    st.session_state["upload_org"] = match[0]
                    st.rerun()
                else:
                    st.error("That passcode didn't match any organization.")

        if org:
            s1, s2 = st.columns([5, 1], vertical_alignment="center")
            s1.success(f"Signed in as **{org}**")
            if s2.button("Sign out"):
                st.session_state.pop("upload_org", None)
                st.rerun()
            if not gh_cfg:
                st.warning("No GitHub token is set up, so uploads only get saved on this server. "
                           "On Streamlit Cloud they'd disappear at the next restart.")

            my_sites = sites_df[sites_df["Organization"] == org]
            st.caption("Your sites: " + (", ".join(f"`{c}` {n}" for c, n in zip(my_sites["SiteCode"], my_sites["SiteName"])) or "none yet. Any site code in your file becomes a new site."))

            template = pd.DataFrame({
                "Date": ["2026-10-18", "2026-10-18"], "Site": ["ABC01", "ABC02"], "DO": [9.1, 8.4], "SPC": [145, 210],
                "PH": [7.4, 7.6], "Turbidity": [2.1, 4.8], "Water Temp": [14.2, 15.9],
            })
            st.download_button("⬇️ Download a template CSV", template.to_csv(index=False).encode(), "monitoring_data_template.csv", "text/csv")
            st.caption("Need at least a **date** and **site code** column plus one of DO (mg/L), conductivity (µS/cm), pH, turbidity (NTU), "
                       "water temp (°C). Your column names don't have to match exactly, you can match them up below.")

            up_key = f"contrib_upload_{st.session_state.get('contrib_n', 0)}"   # new key after a save = empty uploader
            up = st.file_uploader("Your data (CSV)", type="csv", key=up_key)
            if up is not None:
                raw = None
                if getattr(up, "size", 0) > 5 * 1024 * 1024:
                    st.error("That file is over 5 MB. Split it into smaller files please.")
                else:
                    try:
                        raw = pd.read_csv(up)
                        if len(raw.columns) and str(raw.columns[0]).startswith("#"):
                            up.seek(0)
                            raw = pd.read_csv(up, comment="#")
                        raw = raw.dropna(how="all")
                        raw.columns = raw.columns.astype(str).str.strip()
                    except Exception as exc:
                        st.error(f"Couldn't read that file as a CSV. ({exc})")
                        raw = None

                if raw is not None and raw.empty:
                    st.warning("That file doesn't have any rows.")
                elif raw is not None:
                    guess = store.guess_columns(raw.columns)
                    NOT_IN = "(not in my file)"
                    nice = {"Date": "Date", "Site": "Site code", "DO": "Dissolved oxygen (mg/L)", "SPC": "Conductivity (µS/cm)",
                            "PH": "pH", "Turbidity": "Turbidity (NTU)", "Water Temp": "Water temp"}
                    with st.expander("🔗 Match your columns", expanded=not (guess["Date"] and guess["Site"])):
                        opts = [NOT_IN] + list(raw.columns)
                        mapping = {}
                        mcols = st.columns(4)
                        for i, field in enumerate(nice):
                            pick = mcols[i % 4].selectbox(nice[field], opts, index=opts.index(guess[field]) if guess[field] else 0,
                                                          key=f"map_{field}_{up_key}")
                            mapping[field] = None if pick == NOT_IN else pick
                        # header says F? then start with the switch on
                        looks_f = bool(mapping["Water Temp"]) and bool(re.search(r"\(f\)|°\s*f|\bdeg\s*f\b|fahrenheit", mapping["Water Temp"], re.I))
                        temp_f = st.toggle("My water temperatures are in °F (convert them)", value=looks_f, key=f"tf_{up_key}")

                    if not mapping["Date"] or not mapping["Site"]:
                        st.error("Pick which column is the **date** and which is the **site code** above.")
                    elif not any(mapping[p] for p in store.PARAMS):
                        st.error("Match at least one measurement column (DO, conductivity, pH, turbidity or water temp).")
                    else:
                        clean, problems, warns = store.clean_upload(raw, mapping, temp_in_f=temp_f)

                        owner = dict(zip(sites_df["SiteCode"].astype(str).str.upper(), sites_df["Organization"]))
                        codes_in = sorted(clean["Site"].unique()) if len(clean) else []
                        theirs = [c for c in codes_in if c in owner and owner[c] != org]
                        new_codes = [c for c in codes_in if c not in owner]
                        old_codes = [c for c in codes_in if owner.get(c) == org]
                        if theirs:
                            problems.append(f"Skipped site(s) {', '.join(theirs)}: they belong to another organization.")
                            clean = clean[~clean["Site"].isin(theirs)].reset_index(drop=True)
                        clean, n_have = store.drop_existing(clean, all_samples)
                        if n_have:
                            problems.append(f"{n_have} row(s) skipped: there's already data for that site on that date.")

                        u1, u2, u3 = st.columns(3)
                        u1.metric("Rows ready to save", len(clean))
                        u2.metric("Your existing sites", len(old_codes))
                        u3.metric("New sites", len(new_codes))
                        for p_ in problems:
                            st.warning(p_)
                        for w_ in warns:
                            st.info(w_)

                        new_sites = None
                        site_errs = []
                        if new_codes and len(clean):
                            st.markdown("#### New sites in this file")
                            st.caption("Fill these in so the sites can go on the map. Latitude / longitude in decimal degrees "
                                       "(Google Maps → right click the spot → click the numbers to copy them).")
                            blank = pd.DataFrame({"SiteCode": new_codes, "SiteName": [""] * len(new_codes), "Creek": [""] * len(new_codes),
                                                  "Watershed": [""] * len(new_codes), "Latitude": [None] * len(new_codes),
                                                  "Longitude": [None] * len(new_codes), "Notes": [""] * len(new_codes)})
                            new_sites = st.data_editor(
                                blank, hide_index=True, use_container_width=True, disabled=["SiteCode"], key=f"newsites_{up_key}",
                                column_config={
                                    "SiteCode": st.column_config.TextColumn("Site code"),
                                    "SiteName": st.column_config.TextColumn("Site name", required=True),
                                    "Latitude": st.column_config.NumberColumn("Latitude", format="%.6f", min_value=32.0, max_value=42.1),
                                    "Longitude": st.column_config.NumberColumn("Longitude", format="%.6f", min_value=-124.5, max_value=-114.0),
                                },
                            )
                            site_errs = store.check_new_sites(new_sites, sites_df)
                            if site_errs:
                                st.error("Before you can save:\n" + "\n".join(f"- {e_}" for e_ in site_errs))

                        if len(clean):
                            with st.expander(f"Preview ({len(clean)} rows)", expanded=False):
                                st.dataframe(clean, use_container_width=True, hide_index=True)
                            ok_public = st.checkbox("I confirm this data is accurate and OK to show publicly on the dashboard.", key=f"ok_{up_key}")
                            if st.button("💾 Save to the dashboard", type="primary", disabled=not ok_public or bool(site_errs)):
                                with st.spinner("Saving..."):
                                    res = store.save_upload(clean, new_sites if new_codes else None, org, gh_cfg)
                                res["rows"] = len(clean)
                                load_community.clear()
                                st.session_state["last_upload"] = res
                                st.session_state["contrib_n"] = st.session_state.get("contrib_n", 0) + 1
                                st.rerun()
                        else:
                            st.info("Nothing left to save from this file.")
