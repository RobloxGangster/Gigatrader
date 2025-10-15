import streamlit as st
from ui.panels.ml_predict import render

st.set_page_config(page_title="Gigatrader ML Predict Demo", layout="wide")
render(api_base="http://127.0.0.1:8000")
