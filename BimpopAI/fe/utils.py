from typing import Any
import pandas as pd
import streamlit as st
import requests
from urllib.parse import urljoin
import json

BASE_URL = "https://aiybackend.deviationlabs.com/api/v1/"  # APB: why is this not 8080? Dunno? AWS App runner sucks!
# BASE_URL = "http://localhost:8080/api/v1/"
# BASE_URL = "https://srqbimf23j.us-east-1.awsapprunner.comi:8080/api/v1"

DATE_COLUMN = "date/time"
DATA_URL = "https://s3-us-west-2.amazonaws.com/streamlit-demo-data/uber-raw-data-sep14.csv.gz"


def summary(text: str = "") -> str:
    response = requests.post(
        urljoin(BASE_URL, "summarize"),
        headers={"auth": "validated_user"},
        json=dict(summary_question=text),
    )
    return str(json.loads(response.content).get("message", "Something went wrong"))


def priors(text: str = "") -> str:
    response = requests.post(
        urljoin(BASE_URL, "priors"),
        headers={"auth": "validated_user"},
        json=dict(match_on=text),
    )
    return str(json.loads(response.content).get("message", "Something went wrong"))


@st.cache_data  # type: ignore[misc]
def load_data(nrows: int) -> pd.DataFrame:
    data = pd.read_csv(DATA_URL, nrows=nrows)

    def lowercase(x: Any) -> str:
        return str(x).lower()

    data.rename(lowercase, axis="columns", inplace=True)
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN])
    return data
