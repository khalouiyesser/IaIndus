"""
app.py — Service web du DSL Agent (Data Sigma Lean 4.0).

Endpoints :
  GET  /              -> interface web (formulaire opérateur + rapport A3)
  GET  /api/health    -> état du service + présence de la clé API
  POST /api/analyze   -> {domain, form} -> rapport A3 JSON + KPI
  POST /api/a3-pdf    -> {report, kpis} -> téléchargement PDF du rapport A3

La clé API Anthropic est lue côté serveur (variable d'environnement
ANTHROPIC_API_KEY ou fichier .env) — elle n'est JAMAIS exposée au navigateur.
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
)

from src import __version__
from src.config import get_anthropic_key, has_api_key, load_env_file
from src.a3_pdf import build_a3_pdf
from src.dsl_engine import generate_a3

load_env_file()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app")

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)


@app.get("/")
def index() -> str:
    return render_template("index.html", version=__version__)


@app.get("/api/health")
def health() -> Response:
    return jsonify({
        "status": "ok",
        "version": __version__,
        "api_key_configured": has_api_key(),
    })


@app.post("/api/analyze")
def analyze() -> Response:
    payload = request.get_json(silent=True) or {}
    domain = str(payload.get("domain", "quality")).lower()
    form = payload.get("form", {}) or {}

    api_key = get_anthropic_key()
    if not api_key:
        return jsonify({
            "ok": False,
            "error": "Clé API non configurée sur le serveur. "
                     "Définissez la variable d'environnement ANTHROPIC_API_KEY.",
        }), 400

    result = generate_a3(domain, form, api_key)
    status = 200 if result.get("ok") else 502
    return jsonify(result), status


@app.post("/api/a3-pdf")
def a3_pdf() -> Response:
    payload = request.get_json(silent=True) or {}
    report = payload.get("report")
    kpis = payload.get("kpis", {}) or {}

    if not report or not isinstance(report, dict):
        return jsonify({"ok": False, "error": "Rapport A3 manquant ou invalide."}), 400

    try:
        pdf_bytes = build_a3_pdf(report, kpis)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erreur génération PDF")
        return jsonify({"ok": False, "error": f"Erreur PDF : {exc}"}), 500

    title = str(report.get("problem_title", "A3_report")).strip()
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)[:48].strip() or "A3_report"
    filename = f"A3_{safe.replace(' ', '_')}.pdf"

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    logger.info("DSL Agent démarré sur http://0.0.0.0:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
