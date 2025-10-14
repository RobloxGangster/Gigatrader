import numpy as np

from app.data.market import MockDataClient
from app.ml.models import SklearnModel
from app.ml.trainer import latest_feature_row, train_intraday_classifier


def test_training_and_prediction(tmp_path):
    client = MockDataClient()
    metrics = train_intraday_classifier(["AAPL"], client, out_dir=tmp_path)
    assert "AAPL" in metrics

    artifact = next(tmp_path.glob("*.joblib"))
    model = SklearnModel.load(artifact)
    features, _ = latest_feature_row("AAPL", client)
    probs = model.predict_proba(features)
    assert probs.shape[1] == 2
    assert np.isfinite(probs).all()
