import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

# Use a deterministic temp SQLite database and disable external AI/network.
os.environ["DATABASE_URL"] = "sqlite:////tmp/bulk_email_validator_tests.db"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["WORKER_CONCURRENCY"] = "2"
os.environ["JOB_BATCH_SIZE"] = "20"
os.environ["WORKER_RATE_LIMIT_PER_SECOND"] = "1000"
os.environ["RATE_LIMIT_DELAY"] = "0"
os.environ["ENABLE_CATCHALL_PROBE"] = "false"
os.environ["MAX_EMAILS_PER_JOB"] = "100000"
os.environ["RATE_LIMIT_MAX"] = "100000"

import pytest  # noqa: E402

if os.path.exists("/tmp/bulk_email_validator_tests.db"):
    try:
        os.remove("/tmp/bulk_email_validator_tests.db")
    except OSError:
        pass


@pytest.fixture
def app():
    from app import create_app

    application = create_app()
    yield application
    manager = application.extensions.get("job_manager")
    if manager:
        manager.stop()


@pytest.fixture
def client(app):
    return app.test_client()
