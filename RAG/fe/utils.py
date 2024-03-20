import pandas as pd
import streamlit as st
import requests
from urllib.parse import urljoin
import json

BASE_URL = "http://aiy_backend.deviationlabs.com:8080/api/v1/"
#BASE_URL = "http://localhost:8080/api/v1/"
DATE_COLUMN = 'date/time'
DATA_URL = ('https://s3-us-west-2.amazonaws.com/'
            'streamlit-demo-data/uber-raw-data-sep14.csv.gz')

def summary(text:str = "") -> str:
    response = requests.post(
        urljoin(BASE_URL, "summarize"),
        headers={"auth": "validated_user"},
        json=dict(summary_question=text)
    )
    return json.loads(response._content).get("message", "Something went wrong")

def priors(text:str = "") -> str:
    response = requests.post(
        urljoin(BASE_URL, "priors"),
        headers={"auth": "validated_user"},
        json=dict(match_on=text)
    )
    return json.loads(response._content).get("message", "Something went wrong")

@st.cache_data
def load_data(nrows):
    data = pd.read_csv(DATA_URL, nrows=nrows)
    lowercase = lambda x: str(x).lower()
    data.rename(lowercase, axis='columns', inplace=True)
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN])
    return data

