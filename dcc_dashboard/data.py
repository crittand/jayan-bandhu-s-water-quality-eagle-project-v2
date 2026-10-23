"""loads the data every tab works off and hands it over as one `ctx` object.
tabs only ever read from ctx (ctx.data, ctx.miners_ravine ...) - they dont load files themselves,
except Historical which has its own downloads."""
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import site_data_store as store
from dcc_dashboard.shared import BASE_DIR, assay_species

# real field + lab files from the first repo. DONT edit these, the app only reads them
# (the old demo csvs sitting in Raw_data/ aren't used anymore)
REAL_DATA_DIR = BASE_DIR / "Raw_data" / "original"
OUR_SITES = ["JBDC01", "JBDC02"]


# partner uploads (Raw_data/community/). data_version() changes when a file does, so the cache refreshes
@st.cache_data(show_spinner=False)
def load_community(version):
    return store.load_sites(), store.load_samples()


def load_all():
    qpcr = pd.read_csv(REAL_DATA_DIR / "QPCR.csv")
    data = pd.read_csv(REAL_DATA_DIR / "Waterquality.csv").dropna(how="all")
    data.columns = data.columns.str.strip()
    qpcr["Species"] = qpcr["Assay"].apply(assay_species)

    sites_df, community = load_community(store.data_version())
    _orig = data.assign(Organization="Dry Creek Conservancy", UploadBatch="original field data")
    all_samples = pd.concat([_orig, community], ignore_index=True)    # every site, every org
    all_samples["Site"] = all_samples["Site"].astype(str).str.strip().str.upper()
    # concat with an empty/partly empty upload table turns the numbers into object dtype -> regplot etc blow up. force them back
    for _c in store.PARAMS + ["Air Temp(C)", "DO(pct)"]:
        all_samples[_c] = pd.to_numeric(all_samples[_c], errors="coerce")
    # the older tabs are built around our 2 sites, so they get JBDC01/02 rows (original + anything appended later)
    data = all_samples[all_samples["Site"].isin(OUR_SITES)].copy()

    miners_ravine = data[data["Site"] == "JBDC01"].copy()
    dry_creek = data[data["Site"] == "JBDC02"].copy()

    miners_ravine["Date"] = pd.to_datetime(miners_ravine["Date"], format="mixed")
    dry_creek["Date"] = pd.to_datetime(dry_creek["Date"], format="mixed")
    miners_ravine = miners_ravine.sort_values("Date")
    dry_creek = dry_creek.sort_values("Date")

    return SimpleNamespace(
        data=data, qpcr=qpcr, all_samples=all_samples, sites_df=sites_df, community=community,
        miners_ravine=miners_ravine, dry_creek=dry_creek,
    )

