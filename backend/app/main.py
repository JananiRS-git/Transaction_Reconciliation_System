"""Flask application factory."""
from __future__ import annotations

from flask import Flask, g, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

from . import api, config, db


def create_app(db_path=None, default_as_of=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["DB_PATH"] = str(db_path or config.DB_PATH)
    app.config["DEFAULT_AS_OF"] = default_as_of or config.DEFAULT_AS_OF
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_BYTES

    db.init_db(app.config["DB_PATH"])  # creates + seeds only if the database is new

    # Same routes at /reconcile ... (as in the spec) and /api/reconcile ... (used by the UI).
    app.register_blueprint(api.bp, name="root")
    app.register_blueprint(api.bp, url_prefix="/api", name="api_prefixed")

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.errorhandler(HTTPException)
    def http_error(err: HTTPException):
        code = {413: "FILE_TOO_LARGE"}.get(err.code, (err.name or "ERROR").upper().replace(" ", "_"))
        message = ("File is too large (limit 5 MB)." if err.code == 413 else err.description)
        return jsonify({"error": {"code": code, "message": message}}), err.code

    @app.errorhandler(Exception)
    def unexpected(err: Exception):
        app.logger.exception("Unhandled error")
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on the server."}}), 500

    # Optional: serve the built React app (frontend/dist) from the same server.
    dist = config.FRONTEND_DIST
    if (dist / "index.html").exists():
        @app.get("/")
        def index():
            return send_from_directory(dist, "index.html")

        @app.get("/assets/<path:filename>")
        def assets(filename):
            return send_from_directory(dist / "assets", filename)

    return app
