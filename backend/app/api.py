"""REST endpoints. Registered at the root (/reconcile, /transactions, ...) and under /api."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, g, jsonify, request

from . import config, db, domain as d, reconciler, service
from .csv_parser import CsvFormatError, parse_settlement_csv

bp = Blueprint("api", __name__)


# --- helpers -----------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def get_conn():
    if "conn" not in g:
        g.conn = db.connect(current_app.config["DB_PATH"])
    return g.conn


def resolve_as_of() -> date:
    """?as_of=YYYY-MM-DD, else RECON_AS_OF, else today."""
    raw = request.args.get("as_of") or current_app.config.get("DEFAULT_AS_OF")
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(400, "INVALID_AS_OF", f"as_of '{raw}' is not a valid date (use YYYY-MM-DD)")


@bp.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return jsonify({"error": {"code": err.code, "message": err.message}}), err.status


@bp.errorhandler(service.NotFound)
def handle_not_found(err):
    return jsonify({"error": {"code": "NOT_FOUND", "message": str(err)}}), 404


# --- endpoints ---------------------------------------------------------------
@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.post("/reconcile")
def reconcile_endpoint():
    """Process a settlement CSV. Sources (first match wins):
       1. multipart upload, field name 'file'
       2. raw body with Content-Type text/csv or text/plain
       3. use_sample=true (query or form) -> data/settlement_report.csv
    """
    as_of = resolve_as_of()
    upload = request.files.get("file")
    use_sample = (request.args.get("use_sample") or request.form.get("use_sample") or "").lower() in ("1", "true", "yes")

    if upload is not None and upload.filename:
        raw, source = upload.read(), upload.filename
    elif request.mimetype in ("text/csv", "text/plain") and request.get_data():
        raw, source = request.get_data(), "request body"
    elif use_sample:
        path = config.SAMPLE_CSV
        if not path.exists():
            raise ApiError(404, "SAMPLE_NOT_FOUND", "The bundled sample CSV is missing.")
        raw, source = path.read_bytes(), path.name
    else:
        raise ApiError(400, "NO_FILE", "No CSV provided. Upload it as multipart field 'file', "
                                        "send a text/csv body, or pass use_sample=true.")

    try:
        parsed = parse_settlement_csv(raw)
    except CsvFormatError as exc:
        raise ApiError(400, "INVALID_CSV", str(exc))

    conn = get_conn()
    report = reconciler.reconcile(conn, parsed, source)
    views = service.list_transactions(conn, as_of)
    touched = [v for v in service.public_list(views) if v["transaction_id"] in set(report.touched_transaction_ids)]
    return jsonify({
        "source": source,
        "as_of": as_of.isoformat(),
        "summary": report.summary(),
        "results": [o.to_dict() for o in report.outcomes],
        "transactions": touched,
    })


@bp.get("/transactions")
def list_transactions():
    as_of = resolve_as_of()
    status = (request.args.get("status") or "").strip().upper() or None
    if status and status not in d.ALL_STATUSES:
        raise ApiError(400, "INVALID_STATUS", f"status must be one of: {', '.join(d.ALL_STATUSES)}")
    issue = (request.args.get("issue") or "").strip().lower() or None
    if issue and issue not in (d.CRITICAL, d.WARNING, d.NO_ISSUE):
        raise ApiError(400, "INVALID_ISSUE", "issue must be one of: critical, warning, none")
    views = service.list_transactions(get_conn(), as_of, status, issue, request.args.get("q"))
    return jsonify({"as_of": as_of.isoformat(), "count": len(views),
                    "transactions": service.public_list(views)})


@bp.get("/transactions/<transaction_id>")
def transaction_detail(transaction_id: str):
    return jsonify(service.get_transaction_detail(get_conn(), transaction_id, resolve_as_of()))


@bp.get("/dashboard/summary")
def dashboard_summary():
    return jsonify(service.dashboard_summary(get_conn(), resolve_as_of()))


@bp.post("/reset")
def reset_demo_data():
    """Demo helper: drop everything and reload the 14 seed transactions."""
    db.init_db(current_app.config["DB_PATH"], reset=True)
    return jsonify({"status": "reset", "message": "Database reset to the original sample data."})
