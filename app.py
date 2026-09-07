"""Bulk Email Validator Pro — Flask application entrypoint."""

import io
import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from sqlalchemy import Integer, func, select
from werkzeug.utils import secure_filename

from config import Config
from db import get_engine, get_session, utcnow
from extraction import extract_emails_from_file, extract_emails_from_text
from jobs import (
    JobManager,
    create_job,
    export_rows,
    fetch_job,
    fetch_job_events,
    fetch_job_results,
    fetch_jobs,
    job_to_dict,
    shuffle_job,
)
from models import Job, JobEvent, Setting, ValidationResult
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
)

from analyze import ai_configured, analyze_validation_results, generate_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bulk_validator.app")

VALIDATION_STATUSES = {
    DELIVERABILITY_LIKELY,
    INVALID,
    RISKY,
    CATCH_ALL,
    DISPOSABLE,
    ROLE,
    DUPLICATE,
    UNKNOWN,
    ERROR,
    PENDING,
}

EXPORT_TYPES = {
    "VALID",
    "INVALID",
    "RISKY",
    "CATCH_ALL",
    "DISPOSABLE",
    "ROLE",
    "UNKNOWN",
    "DUPLICATE",
    "FULL_REPORT",
    "VALID_EMAILS",
}

EXPORT_DOWNLOAD_NAMES = {
    "VALID": "VALID.csv",
    "INVALID": "INVALID.csv",
    "RISKY": "RISKY.csv",
    "CATCH_ALL": "CATCH_ALL.csv",
    "DISPOSABLE": "DISPOSABLE.csv",
    "ROLE": "ROLE.csv",
    "UNKNOWN": "UNKNOWN.csv",
    "DUPLICATE": "DUPLICATE.csv",
    "FULL_REPORT": "FULL_REPORT.csv",
    "VALID_EMAILS": "VALID_EMAILS.txt",
}

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = Config.RATE_LIMIT_MAX
_request_times = defaultdict(list)


def _rate_limited():
    ip = request.remote_addr or "unknown"
    now = time.time()
    times = [t for t in _request_times[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(times) >= RATE_LIMIT_MAX:
        _request_times[ip] = times
        return True
    times.append(now)
    _request_times[ip] = times
    return False


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )
    app.config.from_object(Config)
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

    allowed_origins = Config.CORS_ORIGINS
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    # Prepare DB.
    get_engine()

    # Background job engine.
    manager = JobManager(app)
    app.extensions["job_manager"] = manager
    manager.start()

    @app.before_request
    def before_request():
        # Only apply to API requests.
        if request.path.startswith("/api/"):
            if _rate_limited():
                return jsonify({"error": "Rate limit exceeded."}), 429

    @app.route("/")
    def index():
        return render_template("index.html", ai_enabled=ai_configured())

    @app.route("/health")
    def health():
        try:
            with get_session() as session:
                count = session.scalar(select(func.count(Job.id))) or 0
            return jsonify(
                {
                    "status": "ok",
                    "service": "bulk-email-validator-pro",
                    "database": "sqlite" if Config.DATABASE_URL.startswith("sqlite") else "external",
                    "jobs": count,
                    "deepseek_ai": ai_configured(),
                }
            )
        except Exception as exc:  # pragma: no cover
            return jsonify({"status": "error", "message": str(exc)}), 500

    @app.route("/api/lookup", methods=["POST"], endpoint="lookup")
    def api_lookup():
        """Single-email immediate validation helper (used for test/quick checks)."""
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email", ""))
        if not email:
            return jsonify({"error": "email is required"}), 400
        from dns_lookup import lookup_domain

        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        dns_result = lookup_domain(domain) if domain else {"error": "Missing domain"}
        result = classify_email(email, dns_result=dns_result)
        result["dns"] = dns_result
        return jsonify(result)

    @app.route("/api/jobs", methods=["POST"], endpoint="create_job")
    def api_create_job():
        """Create a validation job from pasted text, an email list, or an upload."""
        items = []
        name = "Validation Job"
        source_type = "paste"
        overrides = {}

        if request.content_type and request.content_type.startswith("multipart/form-data"):
            source_type = "upload"
            name = request.form.get("name", "Upload Job")
            overrides = _parse_overrides(request.form)
            file = request.files.get("file")
            if file is None or file.filename == "":
                return jsonify({"error": "file is required"}), 400
            safe_name = secure_filename(file.filename or "upload")
            data = file.read()
            if len(data) > Config.MAX_CONTENT_LENGTH:
                return jsonify({"error": "Uploaded file is too large."}), 413
            items = extract_emails_from_file(data, safe_name)
        else:
            data = request.get_json(silent=True) or {}
            name = str(data.get("name", "Validation Job")).strip()[:255] or "Validation Job"
            overrides = _parse_overrides(data)
            emails = data.get("emails")
            text = data.get("text", "")
            source_type = "upload" if data.get("source_type") == "upload" else "paste"
            if isinstance(emails, list):
                source = data.get("source", "paste")
                items = [
                    {"raw_email": normalize_email(str(e)), "source": source or "paste"}
                    for e in emails
                    if str(e).strip()
                ]
            elif isinstance(text, str) and "text" in data:
                items = extract_emails_from_text(text, source="paste")
            elif data.get("source_type") == "upload":
                # An uploaded text is sent as base payload text for direct API use.
                items = extract_emails_from_text(text, source="upload")
            else:
                return jsonify({"error": "Provide emails (array) or text (string)."}), 400

        if not items:
            return jsonify({"error": "No email addresses found in the input."}), 400

        if len(items) > Config.MAX_EMAILS_PER_JOB:
            return (
                jsonify(
                    {
                        "error": (
                            f"Too many submitted rows ({len(items)}). "
                            f"Limit is {Config.MAX_EMAILS_PER_JOB}."
                        )
                    }
                ),
                400,
            )

        try:
            job_id = create_job(app, name=name, source_type=source_type, items=items, config=overrides)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # pragma: no cover
            logger.exception("create job failed")
            return jsonify({"error": f"Could not create job: {exc}"}), 500

        manager.start_job(job_id)
        return jsonify(fetch_job(job_id)), 201

    @app.route("/api/jobs", methods=["GET"], endpoint="list_jobs")
    def api_list_jobs():
        return jsonify({"jobs": fetch_jobs()})

    @app.route("/api/jobs/<int:job_id>", methods=["GET"], endpoint="get_job")
    def api_get_job(job_id):
        job = fetch_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job)

    @app.route("/api/jobs/<int:job_id>/events", methods=["GET"], endpoint="job_events")
    def api_events(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"events": fetch_job_events(job_id)})

    @app.route("/api/jobs/<int:job_id>/start", methods=["POST"], endpoint="start_job")
    def api_start_job(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        job = fetch_job(job_id)
        if job["status"] == "paused":
            manager.resume(job_id)
        else:
            manager.start_job(job_id)
        return jsonify(fetch_job(job_id))

    @app.route("/api/jobs/<int:job_id>/pause", methods=["POST"], endpoint="pause_job")
    def api_pause_job(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        ok = manager.pause(job_id)
        return jsonify(fetch_job(job_id)), (200 if ok else 409)

    @app.route("/api/jobs/<int:job_id>/resume", methods=["POST"], endpoint="resume_job")
    def api_resume_job(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        ok = manager.resume(job_id)
        return jsonify(fetch_job(job_id)), (200 if ok else 409)

    @app.route("/api/jobs/<int:job_id>/stop", methods=["POST"], endpoint="stop_job")
    def api_stop_job(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        ok = manager.stop_job(job_id)
        return jsonify(fetch_job(job_id)), (200 if ok else 409)

    @app.route("/api/jobs/<int:job_id>/results", methods=["GET"], endpoint="results")
    def api_results(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        search = request.args.get("search", "")
        status = request.args.get("status", "")
        domain = request.args.get("domain", "")
        page = int(request.args.get("page", 1) or 1)
        per_page = int(request.args.get("per_page", 50) or 50)
        sort_by = request.args.get("sort_by", "processed_order")
        sort_dir = request.args.get("sort_dir", "asc")
        try:
            payload = fetch_job_results(
                job_id,
                search=search,
                status=status,
                domain=domain,
                page=page,
                per_page=per_page,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )
        except Exception as exc:  # pragma: no cover
            return jsonify({"error": str(exc)}), 400
        return jsonify(payload)

    @app.route(
        "/api/jobs/<int:job_id>/export/<export_type>",
        methods=["GET"],
        endpoint="export",
    )
    def api_export(job_id, export_type):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        export_type = (export_type or "FULL_REPORT").upper()
        if export_type not in EXPORT_TYPES:
            return jsonify({"error": "Unsupported export type."}), 400
        try:
            rows = export_rows(job_id, export_type=export_type)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if export_type == "VALID_EMAILS":
            content = "\n".join(r["email"] for r in rows if r["email"])
            return _text_response(content, EXPORT_DOWNLOAD_NAMES[export_type])
        return _csv_response(rows, EXPORT_DOWNLOAD_NAMES[export_type])

    @app.route("/api/jobs/<int:job_id>/export", methods=["POST"], endpoint="export_selected")
    def api_export_selected(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        data = request.get_json(silent=True) or {}
        export_type = (data.get("export_type") or "FULL_REPORT").upper()
        selected_ids = data.get("ids")
        if selected_ids is not None and not isinstance(selected_ids, list):
            return jsonify({"error": "ids must be an array"}), 400
        if export_type not in EXPORT_TYPES:
            return jsonify({"error": "Unsupported export type."}), 400
        rows = export_rows(job_id, export_type=export_type, selected_ids=selected_ids)
        if export_type == "VALID_EMAILS":
            content = "\n".join(r["email"] for r in rows if r["email"])
            return _text_response(content, EXPORT_DOWNLOAD_NAMES[export_type])
        return _csv_response(rows, EXPORT_DOWNLOAD_NAMES[export_type])

    @app.route("/api/jobs/<int:job_id>/shuffle", methods=["POST"], endpoint="shuffle")
    def api_shuffle(job_id):
        if not fetch_job(job_id):
            return jsonify({"error": "Job not found"}), 404
        data = request.get_json(silent=True) or {}
        seed = data.get("seed")
        rows = shuffle_job(job_id, seed=seed)
        return _csv_response(rows, "SHUFFLED_REPORT.csv")

    @app.route("/api/stats", methods=["GET"], endpoint="stats")
    def api_stats():
        with get_session() as session:
            total_jobs = session.scalar(select(func.count(Job.id))) or 0
            active = session.scalar(
                select(func.count(Job.id)).where(Job.status.in_(["running", "pending", "queued"]))
            ) or 0
        return jsonify({"total_jobs": total_jobs, "active_jobs": active, "ai_enabled": ai_configured()})

    @app.route("/api/analyze", methods=["POST"], endpoint="analyze")
    def api_analyze():
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        if not job_id:
            return jsonify({"error": "job_id is required"}), 400
        job = fetch_job(int(job_id))
        if not job:
            return jsonify({"error": "Job not found"}), 404
        stats = _aggregate_stats(int(job_id))
        domain_stats = _aggregate_domains(int(job_id))
        if ai_configured():
            result = analyze_validation_results(job, stats, domain_stats)
            return jsonify(result)
        return jsonify(generate_report(job, stats, domain_stats))

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify({"error": "Request or upload too large."}), 413

    @app.errorhandler(404)
    def not_found(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        return render_template("index.html", ai_enabled=ai_configured()), 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Method not allowed"}), 405
        return "Method not allowed", 405

    @app.errorhandler(500)
    def server_error(exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        return "Internal server error", 500

    return app


def _parse_overrides(payload) -> dict:
    overrides = {}
    for key in ("concurrency", "batch_size", "dns_timeout", "rate_limit_per_second"):
        val = payload.get(key)
        try:
            overrides[key] = int(val) if val not in (None, "") else None
        except (TypeError, ValueError):
            pass
    overrides = {k: v for k, v in overrides.items() if v is not None}
    return overrides


def _aggregate_stats(job_id: int) -> dict:
    with get_session() as session:
        job = session.get(Job, job_id)
        counts = {
            "pending": 0,
            "deliverability_likely": 0,
            "invalid": 0,
            "risky": 0,
            "catch_all": 0,
            "disposable": 0,
            "role": 0,
            "unknown": 0,
            "error": 0,
        }
        rows = session.execute(
            select(ValidationResult.status, func.count(ValidationResult.id)).where(
                ValidationResult.job_id == job_id,
                ValidationResult.is_duplicate == False,  # noqa: E712
            ).group_by(ValidationResult.status)
        ).all()
        for status, count in rows:
            if status in counts:
                counts[status] = count
        total = sum(counts.values())
        dup = (
            session.scalar(
                select(func.count(ValidationResult.id)).where(
                    ValidationResult.job_id == job_id,
                    ValidationResult.is_duplicate == True,  # noqa: E712
                )
            )
            or 0
        )
        out = {
            "job_id": job_id,
            "submitted": job.submitted_count if job else 0,
            "unique": job.unique_count if job else 0,
            "duplicates": dup,
            "processed": sum(
                v for k, v in counts.items() if k not in ("pending",)
            ),
            "remaining": counts.get("pending", 0),
            **counts,
        }
        denominator = max(1, total)
        for key in ("deliverability_likely", "invalid", "risky", "catch_all", "disposable", "role", "unknown", "error"):
            out[f"{key}_pct"] = counts.get(key, 0) / denominator
        out["duplicates_pct"] = dup / max(1, job.submitted_count if job else 0)
        return out


def _aggregate_domains(job_id: int, limit: int = 25) -> list:
    with get_session() as session:
        rows = session.execute(
            select(
                ValidationResult.domain,
                func.count(ValidationResult.id),
                func.sum((ValidationResult.status == ERROR).cast(Integer)),
                func.sum((ValidationResult.status == UNKNOWN).cast(Integer)),
            )
            .where(
                ValidationResult.job_id == job_id,
                ValidationResult.is_duplicate == False,  # noqa: E712
                ValidationResult.domain != "",
            )
            .group_by(ValidationResult.domain)
            .order_by(func.count(ValidationResult.id).desc())
            .limit(limit)
        ).all()
        return [
            {
                "domain": domain,
                "count": count,
                "error_count": int(error_count or 0),
                "unknown_count": int(unknown_count or 0),
            }
            for domain, count, error_count, unknown_count in rows
        ]


def _csv_response(rows, filename):
    import csv

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Email",
            "Status",
            "Reason",
            "Domain",
            "MX Records",
            "Risk Signals",
            "Checked At",
            "Source",
            "Is Duplicate",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("email", ""),
                row.get("status", ""),
                str(row.get("reason") or ""),
                row.get("domain", ""),
                ", ".join(row.get("mx_records") or []),
                " | ".join(
                    f"{s.get('type', '')}:{s.get('label', '')}" for s in (row.get("risk_signals") or [])
                ),
                row.get("checked_at") or "",
                row.get("source", ""),
                "yes" if row.get("is_duplicate") else "no",
            ]
        )
    return send_file(
        io.BytesIO(buffer.getvalue().encode("utf-8")),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )


def _text_response(content, filename):
    return send_file(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        use_reloader=False,
    )
