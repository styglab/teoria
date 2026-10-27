import pytest


def test_training_uses_holdout_and_only_activity_features():
    pytest.importorskip("sklearn")
    from teoria.features.model_operations.demo_data import generate_customers, FEATURES
    from teoria.features.model_operations.training import fit_customer_churn

    _, rows = generate_customers()
    values = [list(row[2:6]) for row in rows]
    labels = [int(row[6]) for row in rows]
    model, metrics, frame = fit_customer_churn(values, labels)
    assert list(frame.columns) == FEATURES
    assert metrics["training_rows"] == 480 and metrics["evaluation_rows"] == 120
    assert metrics["roc_auc"] >= 0.65
    assert model.predict_proba(frame.head(2)).shape == (2, 2)
