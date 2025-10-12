import streamlit as st
import numpy as np
from utils import load_data, summary, DATE_COLUMN, priors

st.set_page_config(
    page_title="AIY summarizer",
    layout="wide",
    initial_sidebar_state=st.session_state.get("sidebar_state", "collapsed"),
)
st.title("AIY summarizer and data fetcher")


with st.sidebar:
    "This is a sidebar for us to add widgets"

with st.form("summaries_form"):
    input_txt = st.text_area(
        "Get summaries",
        "What has been said so far?",
        height=100,
        max_chars=1000,
    )
    st.write(f"You wrote {len(input_txt)} characters.")

    # Every form must have a submit button.
    submitted = st.form_submit_button("Submit")
    if submitted:
        out = summary(input_txt)
        st.write(out)

with st.form("priors_form"):
    input_txt = st.text_area("Get Priors", "What has been said so far?", height=100, max_chars=1000)
    st.write(f"You wrote {len(input_txt)} characters.")

    # Every form must have a submit button.
    submitted = st.form_submit_button("Submit")
    if submitted:
        out = priors(input_txt)
        st.write(out)

# st.button("Get summary", on_click=summary(input_txt))
# st.link_button("Go to gallery", "https://streamlit.io/gallery")


st.divider()
st.divider()
st.subheader("Old junk")

data = load_data(10000)

if st.checkbox("Show raw data"):
    st.subheader("Raw data")
    st.write(data)

st.subheader("Number of pickups by hour")
hist_values = np.histogram(data[DATE_COLUMN].dt.hour, bins=24, range=(0, 24))[0]
st.bar_chart(hist_values)

# Some number in the range 0-23
hour_to_filter = st.slider("hour", 0, 23, 17)
filtered_data = data[data[DATE_COLUMN].dt.hour == hour_to_filter]

st.subheader("Map of all pickups at %s:00" % hour_to_filter)
st.map(filtered_data)
