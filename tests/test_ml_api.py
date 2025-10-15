
from fastapi.testclient import TestClient
try:
    from backend.api import app  # uvicorn backend.api:app path
except Exception:
    from backend.server import app  # fallback

from services.ml.registry import register_model
from sklearn.linear_model import LogisticRegression
import numpy as np


def test_predict_endpoint():
    X = np.random.randn(40, 4)
    y = (np.random.rand(40) > 0.5).astype(int)
    mdl = LogisticRegression().fit(X, y)
    import numpy as _np
    setattr(mdl, "feature_names_in_", _np.array(list("abcd")))
    register_model("toy_api", mdl, alias="production")

    client = TestClient(app)
    req = {
        "model_name": "toy_api",
        "alias": "production",
        "items": [
            {"symbol":"AAPL","features":{"a":0.1,"b":0.2,"c":0.3,"d":0.4}},
            {"symbol":"MSFT","features":{"a":0.5,"b":0.1,"c":-0.3,"d":0.9}}
        ]
    }
    r = client.post("/ml/predict", json=req)
    assert r.status_code == 200
    body = r.json()
    assert "predictions" in body and len(body["predictions"]) == 2
