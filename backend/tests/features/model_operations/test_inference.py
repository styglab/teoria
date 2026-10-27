import pytest
from pydantic import ValidationError
from teoria.features.model_operations.inference import PredictionInput


def test_inference_contract_rejects_identity_fields_and_out_of_range_values():
    values = dict(
        tenure_months=12, monthly_spend=50, login_days_30d=8, support_tickets_30d=3
    )
    assert PredictionInput(**values).tenure_months == 12
    for changes in (
        {"email": "customer@example.invalid"},
        {"login_days_30d": 31},
        {"tenure_months": True},
        {"monthly_spend": float("nan")},
    ):
        with pytest.raises(ValidationError):
            PredictionInput(**{**values, **changes})
