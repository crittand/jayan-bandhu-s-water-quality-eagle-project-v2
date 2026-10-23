"""salmon event box w/ QR code at the top of every page"""
import io
from datetime import date, datetime
from zoneinfo import ZoneInfo

import segno
import streamlit as st

# change these for the next event. QR code gets made from "url" automatically
SALMON_EVENT = {
    "title": "2026 Salmon Homecoming",
    "when": "Sunday, November 8, 2026",
    "where": "Royer Park, Roseville",
    "url": "https://www.facebook.com/events/1332502405384391",
    "last_day": date(2026, 11, 8),
}

@st.cache_data(show_spinner=False)
def make_qr_png(url: str) -> bytes:
    # error="m" so it still scans when it's small / printed / screenshotted
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=8, border=2, dark="#0B2545")
    return buf.getvalue()


def show(event=SALMON_EVENT):
    today_pacific = datetime.now(ZoneInfo("America/Los_Angeles")).date()  # streamlit cloud runs on UTC!!
    if today_pacific > event["last_day"]:
        return
    with st.container(border=True):
        qr_col, txt_col = st.columns([1, 5], vertical_alignment="center")
        with qr_col:
            st.image(make_qr_png(event["url"]), width=140)
        with txt_col:
            st.markdown(f"#### 🐟 {event['title']}")
            st.markdown(
                f"**{event['when']} · {event['where']}**  \n"
                "Come watch Chinook salmon return to Dry Creek with the Dry Creek Conservancy! "
                "Scan the code with your phone camera, or use the button."
            )
            st.link_button("📅 Event details & RSVP on Facebook", event["url"], type="primary")

