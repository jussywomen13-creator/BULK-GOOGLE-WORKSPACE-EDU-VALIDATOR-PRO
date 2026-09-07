import json
import time

import pytest

from analysis_fixtures import (
    dns_ok,
    dns_slow_ok,
    dns_error,
    fake_jobs_lookup,
    fast_job_config,
)


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "bulk-email-validator-pro"


def test_empty_input(client):
    res = client.post("/api/jobs", json={"text": "   "})
    assert res.status_code == 400
    assert "No email" in res.get_json()["error"]


def test_malformed_input(client):
    res = client.post("/api/jobs", json={})
    assert res.status_code == 400
    assert "Provide emails" in res.get_json()["error"]


def test_create_and_lookup_single(client):
    res = client.post("/api/lookup", json={"email": "nobody@invalid"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] in {"INVALID", "UNKNOWN", "ERROR"}


def test_job_creation_and_export(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_ok)
    payload = "first@example.com\nSECOND@company.com\nfirst@example.com"
    res = client.post("/api/jobs", json={"text": payload})
    assert res.status_code == 201
    job = res.get_json()
    assert job["unique_count"] == 2
    assert job["submitted_count"] == 3
    assert job["duplicate_count"] == 1
    assert job["status"] == "running"

    job_id = job["id"]
    # Wait until the job finishes (small batch).
    for _ in range(50):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] == "completed":
            break
        time.sleep(0.1)
    assert j["status"] == "completed"
    assert j["processed_count"] == 2
    assert j["valid_count"] == 2

    results = client.get(f"/api/jobs/{job_id}/results?per_page=100")
    assert results.status_code == 200
    data = results.get_json()
    assert data["total"] == 3
    statuses = {r["status"] for r in data["items"]}
    assert "DUPLICATE" in statuses
    assert "DELIVERABILITY_LIKELY" in statuses

    exp = client.get(f"/api/jobs/{job_id}/export/FULL_REPORT")
    assert exp.status_code == 200
    assert b"Email" in exp.data
    assert b"DELIVERABILITY_LIKELY" in exp.data

    txt = client.get(f"/api/jobs/{job_id}/export/VALID_EMAILS")
    assert txt.status_code == 200
    assert b"first@example.com" in txt.data
    assert b"second@company.com" in txt.data

    # Selected export and result filtering/sorting.
    first_id = data["items"][0]["id"]
    sel = client.post(f"/api/jobs/{job_id}/export", json={"ids": [first_id], "export_type": "FULL_REPORT"})
    assert sel.status_code == 200
    assert b"Email" in sel.data

    filtered = client.get(f"/api/jobs/{job_id}/results?status=DUPLICATE&per_page=100")
    assert filtered.status_code == 200
    assert filtered.get_json()["total"] == 1

    sorted_results = client.get(f"/api/jobs/{job_id}/results?sort_by=email&sort_dir=desc&per_page=100")
    assert sorted_results.status_code == 200
    assert sorted_results.get_json()["total"] == 3


def test_shuffle_export(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_ok)
    res = client.post("/api/jobs", json={"text": "a@example.com\nb@example.org\na@example.com"})
    job_id = res.get_json()["id"]
    for _ in range(40):
        if client.get(f"/api/jobs/{job_id}").get_json()["status"] == "completed":
            break
        time.sleep(0.1)
    r = client.post(f"/api/jobs/{job_id}/shuffle", json={})
    assert r.status_code == 200
    assert b"Email" in r.data


def test_pause_resume_stop(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_slow_ok)
    fast_job_config(monkeypatch, batch_size=2, concurrency=1)
    res = client.post("/api/jobs", json={"text": "1@example.com\n2@example.com\n3@example.com\n4@example.com"})
    job_id = res.get_json()["id"]

    p = client.post(f"/api/jobs/{job_id}/pause")
    assert p.status_code == 200
    assert p.get_json()["status"] == "paused"

    r = client.post(f"/api/jobs/{job_id}/resume")
    assert r.status_code == 200
    assert r.get_json()["status"] == "running"

    s = client.post(f"/api/jobs/{job_id}/stop")
    assert s.status_code == 200
    assert s.get_json()["status"] == "stopped"


def test_error_timeout_handling(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_error)
    res = client.post("/api/jobs", json={"text": "alpha@example.com"})
    job_id = res.get_json()["id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] == "completed":
            break
        time.sleep(0.1)
    assert j["status"] == "completed"
    assert j["unknown_count"] == 1
    results = client.get(f"/api/jobs/{job_id}/results").get_json()
    assert results["items"][0]["status"] == "UNKNOWN"


def test_60k_scale_simulation(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_ok)
    fast_job_config(monkeypatch, batch_size=1000, concurrency=8, rate=100000)
    emails = [f"user{i}@domain{i % 50}.example" for i in range(60000)]
    payload = "\n".join(emails)
    res = client.post("/api/jobs", json={"text": payload})
    assert res.status_code == 201
    job = res.get_json()
    assert job["unique_count"] == 60000
    job_id = job["id"]
    for _ in range(2000):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] == "completed":
            break
        time.sleep(0.05)
    assert j["status"] == "completed"
    assert j["processed_count"] == 60000


def test_upload_api(client, monkeypatch):
    fake_jobs_lookup(monkeypatch, dns_ok)
    import io

    upload = io.BytesIO(b"name,email\nAlice,alice@example.com\nBob,bob@example.org\n")
    res = client.post(
        "/api/jobs",
        data={"name": "Upload", "file": (upload, "list.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    assert res.get_json()["unique_count"] == 2


def test_deepseek_disabled(client, monkeypatch):
    # Missing DEEPSEEK_API_KEY disables AI but the REST endpoint remains useful.
    res = client.post("/api/analyze", json={})
    assert res.status_code == 400

    fake_jobs_lookup(monkeypatch, dns_ok)
    created = client.post("/api/jobs", json={"text": "ai@example.com"})
    job_id = created.get_json()["id"]
    for _ in range(40):
        j = client.get(f"/api/jobs/{job_id}").get_json()
        if j["status"] == "completed":
            break
        time.sleep(0.1)
    res = client.post("/api/analyze", json={"job_id": job_id})
    assert res.status_code == 200
    data = res.get_json()
    assert data["available"] is False
    assert "report" in data
