
import streamlit as st
import requests
from urllib.parse import urljoin

BASE_URL = "http://aiy_backend.deviationlabs.com:8080/api/v1/"

def summary(text:str) -> str:
    response = requests.post(
        urljoin(BASE_URL, "summarize"),
        headers={"Authorization": "validated_user"},
        json=dict(summary_question=text)
    )
    return response



@st.cache_data
def load_data(nrows):
    data = pd.read_csv(DATA_URL, nrows=nrows)
    lowercase = lambda x: str(x).lower()
    data.rename(lowercase, axis='columns', inplace=True)
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN])
    return data


