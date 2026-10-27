import pytest
from teoria.features.model_operations.demo_data import FEATURES, generate_customers


def test_samples_are_reproducible_and_contacts_cannot_reach_real_people():
    customers, activity = generate_customers()
    assert (customers, activity) == generate_customers()
    assert len(customers) == len(activity) == 600
    assert all(
        row[3].endswith("@example.invalid") and "XXXX" in row[4] and row[-1] is True
        for row in customers
    )
    assert all(row[-1] is True for row in activity)
    assert len({row[1] for row in customers}) == 600
    assert {row[1] for row in customers} == {row[1] for row in activity}
    assert set(row[-2] for row in activity) == {False, True}
    assert set(FEATURES).isdisjoint(
        {
            "full_name",
            "email",
            "phone",
            "birth_date",
            "address",
            "annual_income",
            "credit_score",
            "customer_id",
        }
    )


def test_sample_size_is_bounded():
    with pytest.raises(ValueError):
        generate_customers(1000000)
