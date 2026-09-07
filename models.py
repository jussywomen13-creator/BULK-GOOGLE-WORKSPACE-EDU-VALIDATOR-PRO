"""Database schema for Bulk Email Validator Pro.

SQLAlchemy Core tables are used so the same data layer works with SQLite (local
default) and PostgreSQL (production) without rewriting the application.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = sa.Column(Integer, primary_key=True)
    name = sa.Column(String(255), nullable=False, default="Validation Job")
    source_type = sa.Column(String(50), nullable=False, default="paste")
    status = sa.Column(String(30), nullable=False, default="pending", index=True)

    submitted_count = sa.Column(Integer, nullable=False, default=0)
    unique_count = sa.Column(Integer, nullable=False, default=0)
    duplicate_count = sa.Column(Integer, nullable=False, default=0)
    processed_count = sa.Column(Integer, nullable=False, default=0)
    remaining_count = sa.Column(Integer, nullable=False, default=0)
    valid_count = sa.Column(Integer, nullable=False, default=0)
    invalid_count = sa.Column(Integer, nullable=False, default=0)
    risky_count = sa.Column(Integer, nullable=False, default=0)
    catch_all_count = sa.Column(Integer, nullable=False, default=0)
    disposable_count = sa.Column(Integer, nullable=False, default=0)
    role_count = sa.Column(Integer, nullable=False, default=0)
    unknown_count = sa.Column(Integer, nullable=False, default=0)
    error_count = sa.Column(Integer, nullable=False, default=0)

    progress = sa.Column(Integer, nullable=False, default=0)
    speed = sa.Column(Integer, nullable=False, default=0)
    eta_seconds = sa.Column(Integer, nullable=False, default=0)

    start_time = sa.Column(DateTime, nullable=True)
    completed_time = sa.Column(DateTime, nullable=True)
    error_message = sa.Column(Text, nullable=True)
    config_json = sa.Column(Text, nullable=True)
    retry_count = sa.Column(Integer, nullable=False, default=0)

    created_at = sa.Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = sa.Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_created", "created_at"),
    )


class Email(Base):
    __tablename__ = "emails"

    id = sa.Column(Integer, primary_key=True)
    job_id = sa.Column(Integer, sa.ForeignKey("jobs.id"), nullable=False, index=True)
    raw_email = sa.Column(String(320), nullable=False)
    normalized_email = sa.Column(String(254), nullable=False)
    is_duplicate = sa.Column(Boolean, default=False, nullable=False)
    source = sa.Column(String(500), nullable=False, default="paste")
    unique_key = sa.Column(String(254), nullable=False)
    created_at = sa.Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_emails_job_key", "job_id", "unique_key"),
        Index("ix_emails_job_dup", "job_id", "is_duplicate"),
    )


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id = sa.Column(Integer, primary_key=True)
    job_id = sa.Column(Integer, sa.ForeignKey("jobs.id"), nullable=False, index=True)
    email_id = sa.Column(Integer, sa.ForeignKey("emails.id"), nullable=True, index=True)
    email = sa.Column(String(254), nullable=False)
    status = sa.Column(String(40), nullable=False, default="PENDING", index=True)
    reason = sa.Column(Text, nullable=True)
    domain = sa.Column(String(255), nullable=False, default="", index=True)
    mx_records = sa.Column(Text, nullable=True)
    risk_signals = sa.Column(Text, nullable=True)
    checked_at = sa.Column(DateTime, nullable=True)
    source = sa.Column(String(500), nullable=False, default="paste")
    is_duplicate = sa.Column(Boolean, nullable=False, default=False)
    processed_order = sa.Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_results_job_status", "job_id", "status"),
        Index("ix_results_job_domain", "job_id", "domain"),
        Index("ix_results_job_order", "job_id", "processed_order"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id = sa.Column(Integer, primary_key=True)
    job_id = sa.Column(Integer, sa.ForeignKey("jobs.id"), nullable=False, index=True)
    event_type = sa.Column(String(50), nullable=False)
    message = sa.Column(Text, nullable=True)
    created_at = sa.Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_events_job_time", "job_id", "created_at"),)


class Setting(Base):
    __tablename__ = "settings"

    key = sa.Column(String(255), primary_key=True)
    value = sa.Column(Text, nullable=False)
    created_at = sa.Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = sa.Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
