import time


def dns_ok(domain):
    return {
        "mx": ["mail." + domain],
        "a": ["192.0.2.1"],
        "aaaa": [],
        "has_mx": True,
        "has_a": True,
        "error": None,
    }


def dns_slow_ok(domain):
    time.sleep(0.05)
    return dns_ok(domain)


def dns_error(domain):
    return {
        "mx": [],
        "a": [],
        "aaaa": [],
        "has_mx": False,
        "has_a": False,
        "error": "LifetimeTimeout: DNS lookup failed or timed out",
    }


def fake_jobs_lookup(monkeypatch, fn):
    import jobs

    monkeypatch.setattr(jobs, "lookup_domain", fn)


def fast_job_config(monkeypatch, batch_size=1000, concurrency=8, rate=100000):
    import config
    import jobs

    monkeypatch.setattr(config.Config, "JOB_BATCH_SIZE", batch_size)
    monkeypatch.setattr(config.Config, "WORKER_CONCURRENCY", concurrency)
    monkeypatch.setattr(config.Config, "WORKER_RATE_LIMIT_PER_SECOND", rate)
    monkeypatch.setattr(jobs.Config, "JOB_BATCH_SIZE", batch_size)
    monkeypatch.setattr(jobs.Config, "WORKER_CONCURRENCY", concurrency)
    monkeypatch.setattr(jobs.Config, "WORKER_RATE_LIMIT_PER_SECOND", rate)
