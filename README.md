# Bulk Email Validator Pro

A production-quality web application for legitimate email-list hygiene and
deliverability-potential validation. It processes large lists in background
batches, validates syntax/domain/DNS/MX records, detects common risk signals,
and exports categorized CSVs.

> **Important**: DNS/MX validation only indicates deliverability *potential*.
> It never proves that a specific mailbox exists. This application does **not**
> check Gmail passwords, `email:password` combos, cookies, session tokens,
> login credentials, or attempt mailbox/account login or unauthorized
> enumeration.

## Safety scope

The application performs only:

- Email syntax validation
- Domain format validation
- DNS / MX record lookup
- Disposable-domain detection
- Role-address detection
- Free-provider detection
- Catch-all/risk signals from a conservative verified list (disabled by default)
- Duplicate detection, normalization, and deliverability classification

It never performs credential checking, cookie checking, account takeover,
credential stuffing, CAPTCHA bypass, or unauthorized mailbox enumeration.

## Features

- TXT / CSV upload, paste, and drag-and-drop inputs
- Automatic email extraction from text/CSV
- Normalization, lowercase, whitespace trimming, deduplication
- Background batch processing with pause / resume / stop
- Configurable concurrency, batch size, DNS timeout, and rate limiting
- Live progress, processing speed, ETA, status, start/completion times
- Result table with search, status/domain filters, pagination, sorting, copy,
  row selection, and selected export
- Export: `VALID.csv`, `INVALID.csv`, `RISKY.csv`, `CATCH_ALL.csv`,
  `DISPOSABLE.csv`, `ROLE.csv`, `UNKNOWN.csv`, `DUPLICATE.csv`,
  `FULL_REPORT.csv`, `VALID_EMAILS.txt`
- Shuffle and shuffled-list export
- SQLite by default; PostgreSQL-compatible SQLAlchemy data layer
- Optional DeepSeek AI analysis; the validator works fully without an API key

## Statuses

`DELIVERABILITY_LIKELY`, `INVALID`, `RISKY`, `CATCH_ALL`, `DISPOSABLE`,
`ROLE`, `DUPLICATE`, `UNKNOWN`, `ERROR`, `PENDING`

`DELIVERABILITY_LIKELY` means syntax/domain/DNS checks passed and the domain
has MX/A records. It does **not** mean a specific mailbox exists.

## Quick start (local)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional
python app.py
```

Open `http://localhost:8000`. Health check: `http://localhost:8000/health`.

## Environment variables

See `.env.example`. Key variables:

- `PORT`, `HOST`
- `DATABASE_URL` (`sqlite:///data/email_validator.db` by default)
- `MAX_CONTENT_LENGTH`, `MAX_EMAILS_PER_JOB`
- `JOB_BATCH_SIZE`, `WORKER_CONCURRENCY`, `DNS_TIMEOUT`,
  `WORKER_RATE_LIMIT_PER_SECOND`
- `CORS_ORIGINS`
- `DEEPSEEK_API_KEY` (optional), `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
- `ENABLE_CATCHALL_PROBE` (defaults to `false`; keep it `false` unless you
  supply a verified, consent-based catch-all domain list)

Secrets must be supplied through the environment. Never commit `.env` or real
API keys.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check |
| `POST` | `/api/jobs` | Create/start job from text, array, or multipart file |
| `GET` | `/api/jobs` | List jobs |
| `GET` | `/api/jobs/<id>` | Get one job |
| `POST` | `/api/jobs/<id>/start` | Start a pending/paused job |
| `POST` | `/api/jobs/<id>/pause` | Pause a running job |
| `POST` | `/api/jobs/<id>/resume` | Resume a paused job |
| `POST` | `/api/jobs/<id>/stop` | Stop a job |
| `GET` | `/api/jobs/<id>/results` | Paged, filtered results |
| `GET` | `/api/jobs/<id>/export/<type>` | CSV/TXT export |
| `POST` | `/api/jobs/<id>/export` | Selected export |
| `POST` | `/api/jobs/<id>/shuffle` | Shuffled export |
| `POST` | `/api/analyze` | Aggregate job analysis (DeepSeek or local report) |
| `POST` | `/api/lookup` | Single email quick lookup |

Example job create:

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"name":"Demo","text":"one@example.com\ntwo@example.org"}'
```

## Deployment

### Render

The included `render.yaml` deploys the web service. Set `PORT` automatically
via the platform. For persistent production data, set `DATABASE_URL` to a
managed PostgreSQL URL in the Render dashboard.

### Generic Gunicorn

```bash
gunicorn -b 0.0.0.0:$PORT -w 1 --threads 8 -t 120 --access-logfile - "app:create_app()"
```

A single Gunicorn worker is intentional here because validation batches run in
an in-process background queue. Multiple workers are safe only when paired
with an external queue/worker service.

## Database

Default SQLite file is `data/email_validator.db`. Tables:
`jobs`, `emails`, `validation_results`, `job_events`, `settings`.
Indexes cover job/status/domain/email lookups for large datasets. The data
layer is SQLAlchemy Core/ORM, so PostgreSQL can be used by setting
`DATABASE_URL` without rewriting application code.

## Testing

```bash
. .venv/bin/activate
pytest -q
```

The suite covers health, imports, syntax, extraction, deduplication,
DNS/MX validation, background batch processing, pause/resume/stop, exports,
shuffle, empty/malformed input, error/timeout handling, 60k-scale
simulation, and DeepSeek-disabled behavior.

## License

Available for internal/legitimate list hygiene use.
