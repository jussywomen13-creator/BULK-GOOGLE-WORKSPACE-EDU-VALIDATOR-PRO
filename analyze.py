"""Optional DeepSeek AI analysis layer.

The core validator never requires DeepSeek. If ``DEEPSEEK_API_KEY`` is missing,
the app reports AI as disabled and remains fully functional.

Only aggregated validation results / statistics are sent to DeepSeek. Never
send passwords, cookies, tokens, credentials, or raw mailbox credentials.
"""

import json
import logging

import requests

from config import Config

logger = logging.getLogger("bulk_validator.analyze")


def ai_configured() -> bool:
    return bool(Config.DEEPSEEK_API_KEY)


def _post(payload: dict) -> dict:
    url = f"{Config.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    timeout = 60
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return {"type": "text", "content": content, "usage": data.get("usage", {})}


def _summarize_payload(job, stats, domain_stats) -> dict:
    return {
        "purpose": "Bulk Email Validator Pro aggregated analysis",
        "job": job,
        "stats": stats,
        "domain_stats": domain_stats,
        "note": (
            "DNS/MX validation only indicates deliverability potential; it does not "
            "prove that any specific mailbox exists."
        ),
        "instructions": (
            "Analyze aggregated email list hygiene and deliverability risk signals. "
            "Do not claim specific mailbox existence. Provide a concise structured "
            "English report with strengths, risks, and recommendations."
        ),
    }


def analyze_validation_results(job: dict, stats: dict, domain_stats: list):
    """Analyze aggregate job results with DeepSeek (or nearest offline summary)."""
    if not ai_configured():
        return {
            "available": False,
            "message": "DeepSeek AI is not configured. Set DEEPSEEK_API_KEY to enable.",
        }
    try:
        system = (
            "You are a senior email deliverability analyst. Analyse email list "
            "hygiene metrics. Never claim mailbox existence. Return structured "
            "markdown with sections: Summary, Anomalies, Domain Patterns, "
            "Recommendations."
        )
        user = json.dumps(_summarize_payload(job, stats, domain_stats), ensure_ascii=False)
        payload = {
            "model": Config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
        }
        result = _post(payload)
        result["available"] = True
        return result
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("DeepSeek analysis failed: %s", exc)
        return {
            "available": True,
            "error": f"AI request failed: {exc}",
            "message": "AI analysis could not be completed.",
        }


def summarize_job(job: dict, stats: dict, domain_stats: list):
    return analyze_validation_results(job, stats, domain_stats)


def detect_anomalies(stats: dict, domain_stats: list):
    anomalies = []
    if stats.get("errors", 0) > 0:
        anomalies.append("Some validation attempts returned network/DNS errors.")
    if stats.get("unknown", 0) > 0:
        anomalies.append("DNS/MX records could not be resolved for some domains.")
    high_role_pct = stats.get("role_pct", 0)
    if high_role_pct > 0.2:
        anomalies.append(f"Role addresses are {high_role_pct:.1%} of the list.")
    high_disposable_pct = stats.get("disposable_pct", 0)
    if high_disposable_pct > 0.05:
        anomalies.append(f"Disposable domains are {high_disposable_pct:.1%} of the list.")
    if stats.get("duplicates", 0) > 0:
        anomalies.append(
            f"There are {stats.get('duplicates', 0)} duplicate submissions (deduplicated before validation)."
        )
    for d in domain_stats[:5]:
        if d.get("error_count", 0) > 0:
            anomalies.append(
                f"Domain {d.get('domain')} had {d.get('error_count')} DNS/MX errors."
            )
    return anomalies


def generate_report(job: dict, stats: dict, domain_stats: list):
    """Generate a human-readable offline fallback report when no AI key is set."""
    anomalies = detect_anomalies(stats, domain_stats)
    return {
        "available": False,
        "report": {
            "title": f"Validation Report — {job.get('name', 'Job')}",
            "job": job,
            "stats": stats,
            "top_domains": domain_stats[:10],
            "anomalies": anomalies,
            "summary": (
                f"Processed {stats.get('processed', 0)} unique emails from "
                f"{stats.get('submitted', 0)} submitted rows. "
                f"{stats.get('deliverability_likely', 0)} are likely deliverable; "
                f"{stats.get('invalid', 0)} invalid; "
                f"{stats.get('unknown', 0)} unknown/error. "
                "DNS/MX validation indicates deliverability potential only and does "
                "not verify mailbox existence."
            ),
        },
        "message": "DeepSeek AI is not configured; generated deterministic report.",
    }
