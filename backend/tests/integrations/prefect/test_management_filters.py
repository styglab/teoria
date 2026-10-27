import httpx
from teoria.integrations.prefect.http_client import PrefectManagementClient


def test_default_history_excludes_only_future_scheduled_runs():
    client = PrefectManagementClient(
        httpx.AsyncClient(), "http://prefect/api", "user:password"
    )
    criteria = client.run_filters(["deployment"])["flow_runs"]
    assert criteria["operator"] == "or_"
    assert criteria["state"]["type"]["not_any_"] == ["SCHEDULED"]
    assert "before_" in criteria["expected_start_time"]
    # Cancelled/failed future reservations remain visible as operational history.
    assert client.run_filters(["deployment"], "CANCELLED")["flow_runs"] == {
        "state": {"type": {"any_": ["CANCELLED"]}}
    }
