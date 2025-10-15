import json
import requests
import streamlit as st


def render(api_base: str = "http://127.0.0.1:8000"):
    st.header("ML Predict (Registry-backed)")
    st.caption("Calls /ml/predict using models registered in artifacts/. Use for quick what-if scoring.")

    model_name = st.text_input("Model name", value="toy_api")
    alias = st.text_input("Alias (or leave 'production')", value="production")

    st.subheader("Features")
    st.write("Enter JSON list of items: [{'symbol':'AAPL','features':{'a':0.1,'b':0.2,'c':0.3,'d':0.4}}, ...]")
    default_items = [
        {"symbol":"AAPL","features":{"a":0.1,"b":0.2,"c":0.3,"d":0.4}},
        {"symbol":"MSFT","features":{"a":0.5,"b":0.1,"c":-0.3,"d":0.9}},
    ]
    items_json = st.text_area("Items JSON", value=json.dumps(default_items, indent=2), height=200)

    if st.button("Predict"):
        try:
            items = json.loads(items_json)
            payload = {"model_name": model_name, "alias": alias, "items": items}
            with st.spinner("Calling /ml/predict..."):
                r = requests.post(f"{api_base}/ml/predict", json=payload, timeout=10)
            if r.status_code == 200:
                st.success("OK")
                st.json(r.json())
            else:
                st.error(f"{r.status_code}: {r.text}")
        except Exception as e:
            st.exception(e)
