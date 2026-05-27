"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass
class Settings:
    # Local paths to Excel fixtures (used when Google Sheets API is unavailable)
    posting_base_path: str = os.getenv("POSTING_BASE_PATH", "")
    late_submission_path: str = os.getenv("LATE_SUBMISSION_PATH", "")

    # Google Sheets workbook IDs (production)
    posting_base_workbook_id: str = os.getenv("POSTING_BASE_WORKBOOK_ID", "")
    late_submission_workbook_id: str = os.getenv("LATE_SUBMISSION_WORKBOOK_ID", "")

    # Google service-account credentials path
    google_credentials_path: str = os.getenv(
        "GOOGLE_CREDENTIALS_PATH", "secrets/google-credentials.json"
    )

    # Google Drive roster download settings
    drive_account: str = os.getenv(
        "DRIVE_ACCOUNT", "kantaphajasuwan@airasia.com"
    )
    roster_cache_dir: str = os.getenv("ROSTER_CACHE_DIR", "/data/cache")

    # Database (PostgreSQL via psycopg3)
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://perdiem:perdiem@localhost:5432/perdiem",
    )

    # Web app authentication — single shared admin password (no username)
    # Must be set in production; defaults to a random value so the server
    # starts in dev without a crash (but the random value is not usable).
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")

    # JWT signing secret — auto-generated per process if not set.
    # Set a stable value in production so tokens survive restarts.
    jwt_secret: str = os.getenv("JWT_SECRET", secrets.token_hex(32))
    jwt_expire_hours: int = int(os.getenv("JWT_EXPIRE_HOURS", "8"))

    # File storage paths (shared volume between api + worker containers)
    uploads_dir: str = os.getenv("UPLOADS_DIR", "/data/uploads")
    reports_dir: str = os.getenv("REPORTS_DIR", "/data/reports")

    # CCD payroll/master workbook (staff-ID identity + approved outcomes).
    # Used by the ML dataset builder (PD-ML-002); never read by the engine.
    ccd_master_path: str = os.getenv("CCD_MASTER_PATH", "")

    # ML dataset builder (PD-ML-002). Datasets are PII and stay local: data/ is
    # gitignored. Rate is config-driven so the THB amount is never hard-coded.
    ml_dataset_dir: str = os.getenv("ML_DATASET_DIR", "data/ml/datasets")
    dataset_version: str = os.getenv("DATASET_VERSION", "")
    rate_thb_per_day: int = int(os.getenv("RATE_THB_PER_DAY", "400"))

    # ML eval harness (PD-ML-003). The held-out test month is frozen across
    # experiments so every model reports against the same baseline.
    ml_eval_test_month: str = os.getenv("ML_EVAL_TEST_MONTH", "AUGUST 2025")
    ml_report_dir: str = os.getenv("ML_REPORT_DIR", "data/ml/reports")

    # Triage classifier (PD-ML-004). Disabled by default until validated; the worker
    # falls back to rules-only when off or the model file is missing.
    triage_enabled: bool = os.getenv("TRIAGE_ENABLED", "false").lower() in ("1", "true", "yes")
    triage_model_path: str = os.getenv("TRIAGE_MODEL_PATH", "data/ml/models/triage.json")
    triage_autopass_min_conf: float = float(os.getenv("TRIAGE_AUTOPASS_MIN_CONF", "0.85"))
    triage_review_band: float = float(os.getenv("TRIAGE_REVIEW_BAND", "0.10"))

    # Doc-type / quality classifier (PD-ML-005). Disabled by default until validated;
    # when enabled, acts as a pre-extraction gate — non-VALID images are routed to
    # NEEDS_REVIEW without running Tesseract, saving OCR time on junk attachments.
    doctype_enabled: bool = os.getenv("DOCTYPE_ENABLED", "false").lower() in ("1", "true", "yes")
    doctype_model_path: str = os.getenv("DOCTYPE_MODEL_PATH", "data/ml/models/doctype.json")
    doctype_min_conf: float = float(os.getenv("DOCTYPE_MIN_CONF", "0.70"))

    # Donut roster reader (PD-ML-006). Disabled by default; requires a trained
    # fine-tuned model. Dispatches to torch (HuggingFace model dir) or onnxruntime
    # (*.onnx files in the dir) based on what's present at DONUT_MODEL_PATH.
    donut_enabled: bool = os.getenv("DONUT_ENABLED", "false").lower() in ("1", "true", "yes")
    donut_model_path: str = os.getenv("DONUT_MODEL_PATH", "data/ml/models/donut")
    donut_conf_fallback: float = float(os.getenv("DONUT_CONF_FALLBACK", "0.60"))
    donut_max_pages: int = int(os.getenv("DONUT_MAX_PAGES", "2"))

    # Pluggable extractor backend (PD-ML-007).
    # tesseract (default) | donut (pure ML) | hybrid (ML + Tesseract safety net)
    ocr_backend: str = os.getenv("OCR_BACKEND", "tesseract")
    # OCR result cache — keyed by (file_id, backend, model_version); gitignored.
    ocr_cache_dir: str = os.getenv("OCR_CACHE_DIR", "data/ml/ocr_cache")


settings = Settings()
