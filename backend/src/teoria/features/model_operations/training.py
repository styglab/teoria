"""Demo-only customer churn estimation; personal attributes are never features."""

from .demo_data import FEATURES


def prepare_training_data(values, labels):
    import pandas as pd
    from sklearn.model_selection import train_test_split

    frame = pd.DataFrame(values, columns=FEATURES)
    if len(frame) < 20 or len(frame) != len(labels) or frame.isna().any().any():
        raise ValueError("invalid synthetic training snapshot")
    split = train_test_split(
        frame, labels, test_size=0.2, random_state=42, stratify=labels
    )
    return frame, split


def fit_model(split):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    train_x, _, train_y, _ = split
    model = make_pipeline(
        StandardScaler(), LogisticRegression(random_state=42, max_iter=300)
    )
    model.fit(train_x, train_y)
    return model


def evaluate_model(model, split):
    from sklearn.metrics import accuracy_score, roc_auc_score

    train_x, test_x, _, test_y = split
    metrics = {
        "accuracy": float(accuracy_score(test_y, model.predict(test_x))),
        "roc_auc": float(roc_auc_score(test_y, model.predict_proba(test_x)[:, 1])),
        "training_rows": len(train_x),
        "evaluation_rows": len(test_x),
    }
    if metrics["roc_auc"] < 0.65:
        raise ValueError("synthetic demonstration quality gate failed: ROC AUC < 0.65")
    return metrics


def fit_customer_churn(values: list[list[float]], labels: list[int]):
    frame, split = prepare_training_data(values, labels)
    model = fit_model(split)
    return model, evaluate_model(model, split), frame
