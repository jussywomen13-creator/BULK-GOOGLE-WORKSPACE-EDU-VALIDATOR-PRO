"""Background batch job engine.

Jobs are processed in the background in configurable batch sizes. DNS lookups
are performed concurrently, but each batch is bounded and the job loop can be
paused, resumed, stopped, or requeued. The browser never waits for a 60k list.
"""

import hashlib
import json
import logging
import math
import threading
import time as time_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from queue import Empty, Queue

import sqlalchemy as sa
from sqlalchemy import func, select

from config import Config
from db import get_session, utcnow
from dns_lookup import lookup_domain
from extraction import normalize_and_dedupe
from models import Email, Job, JobEvent, ValidationResult
from validation import (
    DELIVERABILITY_LIKELY,
    DISPOSABLE,
    DUPLICATE,
    ERROR,
    INVALID,
    PENDING,
    RISKY,
    ROLE,
    UNKNOWN,
    CATCH_ALL,
    classify_email,
    normalize_email,
    set_catchall_enabled,
)

logger = logging.getLogger("bulk_validator.jobs")

PASS_THROUGH_STATUSES = (
    DELIVERABILITY_LIKELY,
    INVALID,
    RISKY,
    CATCH_ALL,
    DISPOSABLE,
    ROLE,
    UNKNOWN,
    ERROR,
)


@dataclass
class JobProgress:
    job_id: int
    processed: int = 0
    remaining: int = 0
    valid: int = 0
    invalid: int = 0
    risky: int = 0
    catch_all: int = 0
    disposable: int = 0
    role: int = 0
    unknown: int = 0
    error: int = 0
    duplicate: int = 0
    progress: int = 0
    speed: int = 0
    eta_seconds: int = 0
    status: str = "pending"


class JobManager:
    """Singleton background worker accessed via Flask's ``app.extensions``."""

    def __init__(self, app):
        self.app = app
        self.queue = Queue()
        self.thread = None
        self._lock = threading.Lock()
        self._in_flight = set()
        self._running = False
        self._stop_requested = False
        self._job_rate_info = {}
        set_catchall_enabled(Config.ENABLE_CATCHALL_PROBE)

    # ------------------------------------------------------------------ meta

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_requested = False
        # Re-queue jobs that were running before a restart.
        with get_session() as session:
            session.execute(
                sa.update(Job)
                .where(Job.status.in_(["running", "queued"]))
                .values(status="pending")
            )
            session.commit()
        self.thread = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop_requested = True
        self._running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)

    def _run(self):
        while self._running and not self._stop_requested:
            try:
                job_id = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._process_job(job_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Unexpected worker error for job %s", job_id)
                self._record_event(job_id, "error", "Worker exception processing job.")
            finally:
                self.queue.task_done()
                with self._lock:
                    self._in_flight.discard(job_id)

    # ---------------------------------------------------------------- public

    def enqueue_job(self, job_id: int, start_now: bool = True) -> bool:
        with self._lock:
            if job_id in self._in_flight:
                return False
            self._in_flight.add(job_id)
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                with self._lock:
                    self._in_flight.discard(job_id)
                return False
            now = utcnow()
            if job.status in ("completed", "stopped", "paused"):
                with self._lock:
                    self._in_flight.discard(job_id)
                return False
            if start_now and job.status == "pending":
                job.status = "running"
                if not job.start_time:
                    job.start_time = now
                session.add(
                    JobEvent(job_id=job.id, event_type="job_started", message="Job started.")
                )
            elif job.status == "queued":
                job.status = "running"
                if not job.start_time:
                    job.start_time = now
            session.commit()
        if start_now:
            self.queue.put(job_id)
        return True

    # ---------------------------------------------------------------- actions

    def start_job(self, job_id: int):
        return self.enqueue_job(job_id, start_now=True)

    def resume(self, job_id: int):
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return False
            if job.status not in ("paused", "pending"):
                return False
            job.status = "running"
            if not job.start_time:
                job.start_time = utcnow()
            session.add(JobEvent(job_id=job.id, event_type="job_resumed", message="Job resumed."))
            session.commit()
        self.queue.put(job_id)
        return True

    def pause(self, job_id: int):
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return False
            if job.status in ("completed", "stopped"):
                return False
            job.status = "paused"
            session.add(JobEvent(job_id=job.id, event_type="job_paused", message="Job paused."))
            session.commit()
        return True

    def stop_job(self, job_id: int):
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return False
            if job.status in ("completed", "stopped"):
                return False
            job.status = "stopped"
            job.completed_time = utcnow()
            job.speed = 0
            job.eta_seconds = 0
            session.add(JobEvent(job_id=job.id, event_type="job_stopped", message="Job stopped."))
            session.commit()
        return True

    def _process_job(self, job_id: int):
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job or job.status != "running":
                return
            current_count = job.processed_count
            start_ts = time_module.monotonic()

        batch = self._fetch_batch(job_id)
        if not batch:
            self._finalize_if_complete(job_id)
            return

        # Bounded concurrent DNS work; each row is independent.
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, Config.WORKER_CONCURRENCY)) as ex:
            futures = {
                ex.submit(self._validate_row, row["email"], row["domain"]): row
                for row in batch
            }
            for future in as_completed(futures):
                row = futures[future]
                results[row["id"]] = future.result()

        elapsed = max(0.001, time_module.monotonic() - start_ts)
        # Basic rate-limit shaping: keep batches spaced to the configured limit.
        target_rate = max(1, Config.WORKER_RATE_LIMIT_PER_SECOND)
        min_seconds = len(batch) / float(target_rate)
        if elapsed < min_seconds:
            time_module.sleep(min_seconds - elapsed)

        self._apply_results(job_id, results)

        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return
            new_processed = job.processed_count
            remaining = max(0, job.unique_count - new_processed)
            job.remaining_count = remaining
            if remaining <= 0:
                job.status = "completed"
                job.progress = 100
                job.completed_time = utcnow()
                session.add(
                    JobEvent(job_id=job.id, event_type="job_completed", message="Job completed.")
                )
            else:
                job.progress = min(
                    99,
                    int(round((new_processed / max(1, job.unique_count)) * 100)),
                )
                speed = int(len(batch) / elapsed)
                job.speed = max(0, speed)
                remaining_uniq = max(0, job.unique_count - new_processed)
                job.eta_seconds = int(remaining_uniq / max(1, speed)) if speed > 0 else 0
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event_type="batch_complete",
                        message=f"Processed {len(batch)} records; processed={new_processed}, remaining={remaining}.",
                    )
                )
            session.commit()

        if self._should_continue(job_id):
            self.queue.put(job_id)

    # Internal private helpers ---------------------------------------------

    def _fetch_batch(self, job_id):
        with get_session() as session:
            rows = session.execute(
                select(ValidationResult)
                .where(
                    ValidationResult.job_id == job_id,
                    ValidationResult.is_duplicate == False,  # noqa: E712
                    ValidationResult.status == PENDING,
                )
                .order_by(ValidationResult.processed_order.asc())
                .limit(max(1, Config.JOB_BATCH_SIZE))
            ).scalars().all()
            return [
                {
                    "id": r.id,
                    "email": r.email,
                    "domain": r.domain or "",
                }
                for r in rows
            ]

    def _validate_row(self, email: str, domain: str) -> dict:
        if not domain:
            normalized = normalize_email(email)
            domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
        dns_result = {}
        if domain:
            dns_result = lookup_domain(domain)
        result = classify_email(email, dns_result=dns_result)
        try:
            result["dns"] = dns_result
        except Exception:  # pragma: no cover
            pass
        return result

    def _apply_results(self, job_id: int, results: dict):
        now = utcnow()
        with get_session() as session:
            for row_id, result in results.items():
                session.execute(
                    sa.update(ValidationResult)
                    .where(ValidationResult.id == row_id)
                    .values(
                        status=result["status"],
                        reason=result.get("reason", ""),
                        domain=result.get("domain", ""),
                        mx_records=json.dumps(result.get("mx_records", []), ensure_ascii=False),
                        risk_signals=json.dumps(
                            result.get("risk_signals", []), ensure_ascii=False
                        ),
                        checked_at=now,
                    )
                )
            session.commit()

        counters = self._recount(job_id)
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return
            for field, value in counters.items():
                setattr(job, field, value)
            session.commit()

    def _recount(self, job_id: int) -> dict:
        counts = {
            "processed_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "risky_count": 0,
            "catch_all_count": 0,
            "disposable_count": 0,
            "role_count": 0,
            "unknown_count": 0,
            "error_count": 0,
            "duplicate_count": 0,
        }
        with get_session() as session:
            status_rows = session.execute(
                select(ValidationResult.status, func.count(ValidationResult.id))
                .where(
                    ValidationResult.job_id == job_id,
                    ValidationResult.is_duplicate == False,  # noqa: E712
                )
                .group_by(ValidationResult.status)
            ).all()
            for status, count in status_rows:
                if status == DELIVERABILITY_LIKELY:
                    counts["valid_count"] += count
                elif status == INVALID:
                    counts["invalid_count"] += count
                elif status == RISKY:
                    counts["risky_count"] += count
                elif status == CATCH_ALL:
                    counts["catch_all_count"] += count
                elif status == DISPOSABLE:
                    counts["disposable_count"] += count
                elif status == ROLE:
                    counts["role_count"] += count
                elif status == UNKNOWN:
                    counts["unknown_count"] += count
                elif status == ERROR:
                    counts["error_count"] += count
                elif status == PENDING:
                    continue

            dup_count = session.scalar(
                select(func.count(ValidationResult.id)).where(
                    ValidationResult.job_id == job_id,
                    ValidationResult.is_duplicate == True,  # noqa: E712
                )
            ) or 0
            counts["duplicate_count"] = dup_count
            counts["processed_count"] = sum(
                counts[k]
                for k in (
                    "valid_count",
                    "invalid_count",
                    "risky_count",
                    "catch_all_count",
                    "disposable_count",
                    "role_count",
                    "unknown_count",
                    "error_count",
                )
            )
        return counts

    def _finalize_if_complete(self, job_id: int):
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job or job.status != "running":
                return
            remaining = job.unique_count - job.processed_count
            if remaining <= 0:
                job.status = "completed"
                job.progress = 100
                job.completed_time = utcnow()
                job.speed = 0
                job.eta_seconds = 0
                session.add(
                    JobEvent(job_id=job.id, event_type="job_completed", message="Job completed.")
                )
                session.commit()

    def _should_continue(self, job_id: int) -> bool:
        with get_session() as session:
            job = session.get(Job, job_id)
            if not job:
                return False
            return job.status == "running"

    def _record_event(self, job_id: int, event_type: str, message: str):
        try:
            with get_session() as session:
                session.add(JobEvent(job_id=job_id, event_type=event_type, message=message))
                session.commit()
        except Exception:  # pragma: no cover
            logger.exception("Could not record job event %s/%s", job_id, event_type)

# ------------------------------------------------------------------ creation

def create_job(app, name: str, source_type: str, items: list, config: dict | None = None):
    """Persist a job, its raw email rows, and a result row per occurrence."""
    dedup = normalize_and_dedupe(items)
    if dedup["total"] == 0:
        raise ValueError("No valid email addresses found in the input.")

    config = config or {}
    job_config = {
        "concurrency": Config.WORKER_CONCURRENCY,
        "batch_size": Config.JOB_BATCH_SIZE,
        "dns_timeout": Config.DNS_TIMEOUT,
        "rate_limit_per_second": Config.WORKER_RATE_LIMIT_PER_SECOND,
        "catchall_probe_enabled": Config.ENABLE_CATCHALL_PROBE,
    }
    job_config.update(config)

    with get_session() as session:
        job = Job(
            name=(name or "Validation Job").strip()[:255] or "Validation Job",
            source_type=source_type,
            submitted_count=dedup["total"],
            unique_count=dedup["unique"],
            duplicate_count=dedup["duplicates"],
            remaining_count=dedup["unique"],
            status="pending",
            config_json=json.dumps(job_config, ensure_ascii=False, sort_keys=True),
        )
        session.add(job)
        session.flush()

        email_rows = []
        result_rows = []
        order = 0
        for item in dedup["items"]:
            order += 1
            email_rows.append(
                {
                    "job_id": job.id,
                    "raw_email": item["raw_email"],
                    "normalized_email": item["normalized"],
                    "is_duplicate": item["is_duplicate"],
                    "source": item["source"],
                    "unique_key": hashlib.sha1(item["unique_key"].encode("utf-8")).hexdigest(),
                    "created_at": utcnow(),
                }
            )
            if item["is_duplicate"]:
                result_rows.append(
                    {
                        "job_id": job.id,
                        "email": item["normalized"],
                        "status": DUPLICATE,
                        "reason": "Duplicate of a previously seen normalized email.",
                        "domain": item["domain"],
                        "source": item["source"],
                        "is_duplicate": True,
                        "processed_order": order,
                        "checked_at": utcnow(),
                    }
                )
            else:
                result_rows.append(
                    {
                        "job_id": job.id,
                        "email": item["normalized"],
                        "status": PENDING,
                        "reason": "Queued for DNS/MX validation.",
                        "domain": item["domain"],
                        "source": item["source"],
                        "is_duplicate": False,
                        "processed_order": order,
                    }
                )

        # Bulk inserts keep 60k+ submission startup fast.
        session.execute(sa.insert(Email.__table__), email_rows)
        session.execute(sa.insert(ValidationResult.__table__), result_rows)
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="job_created",
                message=f"Created job with {dedup['total']} submitted, {dedup['unique']} unique, {dedup['duplicates']} duplicate(s).",
            )
        )
        session.commit()
        return job.id


# ------------------------------------------------------------------ read API

def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "name": job.name,
        "source_type": job.source_type,
        "status": job.status,
        "submitted_count": job.submitted_count,
        "unique_count": job.unique_count,
        "duplicate_count": job.duplicate_count,
        "processed_count": job.processed_count,
        "remaining_count": job.remaining_count,
        "valid_count": job.valid_count,
        "invalid_count": job.invalid_count,
        "risky_count": job.risky_count,
        "catch_all_count": job.catch_all_count,
        "disposable_count": job.disposable_count,
        "role_count": job.role_count,
        "unknown_count": job.unknown_count,
        "error_count": job.error_count,
        "progress": job.progress,
        "speed": job.speed,
        "eta_seconds": job.eta_seconds,
        "start_time": job.start_time.isoformat() if job.start_time else None,
        "completed_time": job.completed_time.isoformat() if job.completed_time else None,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def fetch_jobs(limit: int = 100, include_history: bool = True):
    with get_session() as session:
        q = select(Job).order_by(Job.created_at.desc()).limit(min(500, max(1, limit)))
        return [job_to_dict(j) for j in session.scalars(q).all()]


def fetch_job(job_id: int):
    with get_session() as session:
        return job_to_dict(session.get(Job, job_id))


def fetch_job_events(job_id: int, limit: int = 100):
    with get_session() as session:
        q = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.desc())
            .limit(min(500, max(1, limit)))
        )
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "message": e.message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in session.scalars(q).all()
        ]


def fetch_job_results(
    job_id: int,
    search: str = "",
    status: str = "",
    domain: str = "",
    page: int = 1,
    per_page: int = 50,
    sort_by: str = "processed_order",
    sort_dir: str = "asc",
):
    per_page = min(500, max(1, per_page))
    page = max(1, page)
    sort_columns = {
        "processed_order": ValidationResult.processed_order,
        "email": ValidationResult.email,
        "domain": ValidationResult.domain,
        "status": ValidationResult.status,
        "checked_at": ValidationResult.checked_at,
    }
    col = sort_columns.get(sort_by, ValidationResult.processed_order)
    if sort_dir == "desc":
        col = col.desc()

    with get_session() as session:
        base = select(ValidationResult).where(ValidationResult.job_id == job_id)
        if search:
            like = f"%{search.strip()}%"
            base = base.where(
                sa.or_(
                    ValidationResult.email.ilike(like),
                    ValidationResult.domain.ilike(like),
                    ValidationResult.reason.ilike(like),
                )
            )
        if status and status.strip().upper() in {*PASS_THROUGH_STATUSES, DUPLICATE, PENDING}:
            base = base.where(ValidationResult.status == status.strip().upper())
        if domain and domain.strip():
            base = base.where(ValidationResult.domain == domain.strip().lower())

        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        base = base.order_by(col)
        rows = (
            session.execute(base.offset((page - 1) * per_page).limit(per_page))
            .scalars()
            .all()
        )

        result = []
        for r in rows:
            mx = []
            try:
                mx = json.loads(r.mx_records or "[]")
            except Exception:
                mx = []
            signals = []
            try:
                signals = json.loads(r.risk_signals or "[]")
            except Exception:
                signals = []
            result.append(
                {
                    "id": r.id,
                    "email": r.email,
                    "status": r.status,
                    "reason": r.reason,
                    "domain": r.domain,
                    "mx_records": mx,
                    "risk_signals": signals,
                    "checked_at": r.checked_at.isoformat() if r.checked_at else None,
                    "source": r.source,
                    "is_duplicate": r.is_duplicate,
                }
            )
        return {
            "items": result,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": int(math.ceil(total / float(per_page))) if per_page else 0,
        }


def _result_to_export_row(r: ValidationResult) -> dict:
    mx = []
    try:
        mx = json.loads(r.mx_records or "[]")
    except Exception:
        mx = []
    signals = []
    try:
        signals = json.loads(r.risk_signals or "[]")
    except Exception:
        signals = []
    return {
        "id": r.id,
        "email": r.email,
        "status": r.status,
        "reason": r.reason,
        "domain": r.domain,
        "mx_records": mx,
        "risk_signals": signals,
        "checked_at": r.checked_at.isoformat() if r.checked_at else None,
        "source": r.source,
        "is_duplicate": r.is_duplicate,
    }


def export_rows(job_id: int, export_type: str | None = None, selected_ids: list | None = None):
    export_type = (export_type or "FULL_REPORT").upper()
    with get_session() as session:
        q = select(ValidationResult).where(ValidationResult.job_id == job_id)
        if selected_ids:
            q = q.where(ValidationResult.id.in_(selected_ids))
        if export_type == "VALID":
            q = q.where(ValidationResult.status == DELIVERABILITY_LIKELY)
        elif export_type == "INVALID":
            q = q.where(ValidationResult.status == INVALID)
        elif export_type == "RISKY":
            q = q.where(ValidationResult.status == RISKY)
        elif export_type == "CATCH_ALL":
            q = q.where(ValidationResult.status == CATCH_ALL)
        elif export_type == "DISPOSABLE":
            q = q.where(ValidationResult.status == DISPOSABLE)
        elif export_type == "ROLE":
            q = q.where(ValidationResult.status == ROLE)
        elif export_type == "UNKNOWN":
            q = q.where(ValidationResult.status == UNKNOWN)
        elif export_type == "DUPLICATE":
            q = q.where(ValidationResult.status == DUPLICATE)
        elif export_type == "FULL_REPORT":
            pass
        elif export_type == "VALID_EMAILS":
            q = q.where(ValidationResult.status == DELIVERABILITY_LIKELY)
        else:
            raise ValueError(f"Unsupported export type: {export_type}")
        rows = session.execute(q.order_by(ValidationResult.processed_order.asc())).scalars().all()
    return [_result_to_export_row(r) for r in rows]


def shuffle_job(job_id: int, selected_only: bool = False, seed: int | None = None):
    """Return shuffled result rows for export.

    The database is not mutated; the returned list is randomized and suitable
    for export of a randomized list.
    """
    import random

    with get_session() as session:
        q = select(ValidationResult).where(ValidationResult.job_id == job_id)
        if selected_only:
            # selected_only requires ids; not used at this level.
            pass
        rows = session.scalars(q).all()
    rng = random.Random(seed)
    rng.shuffle(rows)
    return [_result_to_export_row(r) for r in rows]
