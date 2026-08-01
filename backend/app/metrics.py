"""
Module: metrics

Prometheus metric definitions, scraped via the /metrics endpoint
(I-M requirements; solution-architecture.md "Required metrics"). Business
event counters are incremented from the service layer at the point each
event occurs, rather than inferred generically from HTTP traffic, so the
figures reflect real domain events (requirement lifecycle, change request
outcomes, login attempts).
"""

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status_code"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)

requirements_created_total = Counter("requirements_created_total", "Requirements created")
requirements_updated_total = Counter("requirements_updated_total", "Requirement versions created")
requirements_approved_total = Counter("requirements_approved_total", "Requirements approved")
requirements_completed_total = Counter("requirements_completed_total", "Requirements completed")
requirements_archived_total = Counter("requirements_archived_total", "Requirements archived")

change_requests_submitted_total = Counter("change_requests_submitted_total", "Change requests submitted")
change_requests_approved_total = Counter("change_requests_approved_total", "Change requests approved")
change_requests_rejected_total = Counter("change_requests_rejected_total", "Change requests rejected")

login_attempts_total = Counter("login_attempts_total", "Login attempts", ["result"])
