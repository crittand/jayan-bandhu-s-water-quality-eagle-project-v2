"""sidebar: tab picker + the quick guide"""
import streamlit as st

from dcc_dashboard import tabs


def show():
    """draws the sidebar, returns the key of the tab that's picked"""
    tab_keys = list(tabs.TABS)
    with st.sidebar:
        st.header("🧭 Dashboard Navigation")
        labels = [tabs.label(k) for k in tab_keys]
        # other tabs can jump here by setting st.session_state.pending_tab = "<tab key>" + st.rerun()
        # (overview map does this)
        want = st.session_state.pop("pending_tab", None)
        if want in tab_keys:
            st.session_state.nav_tab = tabs.label(want)
        if st.session_state.get("nav_tab") not in labels:
            st.session_state.nav_tab = labels[0]
        # using a key (instead of index=) so one click always switches the tab
        picked = st.radio("Select Tab", labels, key="nav_tab")
        picked = tab_keys[labels.index(picked)]

        st.divider()
        st.markdown(
            "**🌲 Quick Guide to the 5 Vital Signs**\n"
            "*(Monthly sensors loaned by **Sierra Streams Institute**)*:\n"
            "- **DO (Dissolved Oxygen):** Breathable oxygen for salmon (`>= 7 mg/L` is healthy).\n"
            "- **Conductivity (SPC):** Dissolved minerals & urban storm runoff (`< 200 µS/cm` is healthy).\n"
            "- **pH:** Acidity/alkalinity balance (`6.5 – 8.5` is healthy).\n"
            "- **Turbidity:** Water clarity vs. mud/sediment (`< 10 NTU` is clear).\n"
            "- **Water Temp:** Cool water keeps salmon alive (`10 – 20 °C` is sustainable).\n\n"
            "**🧬 Two eDNA Tracks:**\n"
            "- **BMI Metabarcoding:** Processed by **CALeDNA Lab at UCSC**, shared on **eDNA Explorer**.\n"
            "- **Invasive qPCR:** **New Zealand Mudsnails** & **Asian Clams** analyzed by **Jonah Ventures**."
        )
    return picked
