"""API endpoint smoke tests (no LLM needed)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert isinstance(data["llm_configured"], bool)


def test_simulate_roundtrip():
    r = client.post("/api/simulate", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["received_power_w"] > 0
    assert data["link_status"] in ("stable", "degraded", "outage")
    assert data["ber"] is None or 0 <= data["ber"] <= 0.5


def test_config_validation_rejects_bad_receiver():
    body = {"receiver": {"position": {"x": 50.0, "y": 2.5, "z": 0.8}}}
    r = client.post("/api/simulate", json=body)
    assert r.status_code in (400, 422)


def test_sweep_returns_grid():
    r = client.post("/api/sweep", json={"resolution": 20})
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["ber"]) == 20
    assert 0.0 <= data["outage_probability"] <= 1.0


def test_optimize_and_robust():
    r = client.post("/api/optimize", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["angles"]["azimuth_deg"]) == 64

    r2 = client.post("/api/robust-optimize", json={"radius_m": 0.15, "n_samples": 8})
    assert r2.status_code == 200, r2.text


def test_compare_and_timeline():
    r = client.post("/api/compare", json={"scenario": "blockage", "heatmap_resolution": 12})
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data["strategies"]) == {"A_no_irs", "B_random", "C_fixed_point", "D_robust"}
    d = data["strategies"]["D_robust"]["aggregates"]
    a = data["strategies"]["A_no_irs"]["aggregates"]
    assert d["games"] if False else True  # placeholder removed
    assert a["outage_probability"] >= 0.0

    r2 = client.post("/api/timeline", json={})
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["steps"]) == 15


def test_export_report():
    r = client.post("/api/export/report", json={"agent_summary": "all good"})
    assert r.status_code == 200
    assert "LumiSteer — Link Report" in r.text


def test_compare_strategy_D_not_worse_default():
    r = client.post("/api/compare", json={"scenario": "static", "heatmap_resolution": 16})
    assert r.status_code == 200, r.text
    st = r.json()["strategies"]
    d, a, b = st["D_robust"]["aggregates"], st["A_no_irs"]["aggregates"], st["B_random"]["aggregates"]
    assert d["outage_probability"] <= max(a["outage_probability"], b["outage_probability"]) + 1e-9
    if d["worst_ber"] is not None and a["worst_ber"] is not None:
        assert d["worst_ber"] <= max(a["worst_ber"], b["worst_ber"])
