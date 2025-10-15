
from services.ml.registry import register_model, list_models, load_model, promote_alias
from sklearn.linear_model import LogisticRegression
import numpy as np, uuid, os


def test_registry_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / ("artifacts_" + uuid.uuid4().hex)))
    X = np.random.randn(60, 3)
    y = (np.random.rand(60) > 0.5).astype(int)
    model = LogisticRegression().fit(X, y)
    meta = register_model("toy", model, metrics={"auc":0.5}, tags={"t":"u"}, alias="production")
    idx = list_models("toy")
    assert len(idx["models"]["toy"]) >= 1
    loaded = load_model("toy", alias="production")
    assert hasattr(loaded, "predict_proba")
    promote_alias("toy", meta.version, alias="production")
