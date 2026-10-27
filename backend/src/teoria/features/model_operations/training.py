"""Demo-only customer churn estimation; personal attributes are never features."""

from .demo_data import FEATURES


def fit_customer_churn(values: list[list[float]], labels: list[int]):
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    frame = pd.DataFrame(values, columns=FEATURES)
    train_x, test_x, train_y, test_y = train_test_split(
        frame, labels, test_size=0.2, random_state=42, stratify=labels
    )
    model = make_pipeline(
        StandardScaler(), LogisticRegression(random_state=42, max_iter=300)
    )
    model.fit(train_x, train_y)
    metrics = {
        "accuracy": float(accuracy_score(test_y, model.predict(test_x))),
        "roc_auc": float(roc_auc_score(test_y, model.predict_proba(test_x)[:, 1])),
        "training_rows": len(train_x),
        "evaluation_rows": len(test_x),
    }
    if metrics["roc_auc"] < 0.65:
        raise ValueError("synthetic demonstration quality gate failed")
    return model, metrics, frame
