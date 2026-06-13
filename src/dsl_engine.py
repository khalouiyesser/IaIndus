"""
dsl_engine.py — Moteur du DSL Agent (Data Sigma Lean 4.0).

Prend les données d'un formulaire opérateur (domaine Quality / Maintenance /
Flow) et génère un rapport Digital A3 structuré (8 sections PDCA) via l'API
Anthropic, avec fallback de modèles et retry exponentiel.

Sortie : dict Python prêt à être sérialisé en JSON pour le frontend ET réutilisé
pour la génération PDF/HTML.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from src.config import (
    CLAUDE_MODELS,
    FALLBACK_PAUSE,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    RETRY_BACKOFF,
    RETRY_DELAY,
    TEMPERATURE,
)

logger = logging.getLogger(__name__)


# ── Prompt système — format Digital A3 ──────────────────────────────────────
SYSTEM_PROMPT = """You are DSL Agent — an expert industrial engineer specialized \
in Lean Manufacturing, Six Sigma, and DMAIC problem-solving. You analyze \
production data and generate complete Digital A3 reports.

The Digital A3 is a structured Lean problem-solving document with 8 sections \
mapped to the PDCA cycle. Your output must follow this exact format.

RETURN ONLY a valid JSON object — no markdown, no extra text, no code fences:
{
  "sigma_level": "X.X sigma",
  "dpmo": 000000,
  "domain": "Quality/Maintenance/Flow",
  "problem_title": "Short problem title (max 10 words)",
  "problem_summary": "One sentence summary of the core problem",
  "background": "S1-2 BACKGROUND & CURRENT CONDITION: Why this problem matters (business impact, COPQ/cost/delivery risk) + current KPI baseline with all calculated values (defect rate, DPMO, OEE A*P*Q, lead time gap, Takt time analysis). Be quantitative — use the operator's data directly.",
  "target": "S3-4 TARGET CONDITION & CTQ: Specific SMART improvement objective (reduce X from A to B by date) + CTQ characteristic (what must be achieved and how it will be measured). Include target KPI values.",
  "rootcause": "S5 ROOT CAUSE ANALYSIS: Complete 5 Whys chain (5 levels, each Why answered with evidence from operator data) + 5M Fishbone summary (Machine/Method/Man/Material/Milieu — each marked CONFIRMED/PROBABLE/NOT CONFIRMED with evidence). End with a clear Root Cause Statement.",
  "countermeasures": "S6-7 COUNTERMEASURES & IMPLEMENTATION PLAN: For each confirmed root cause, specify: the Lean/Six Sigma tool used, the specific action, the responsible role, and the expected impact. Then give a week-by-week implementation timeline.",
  "control": "S8 RESULTS MONITORING & FOLLOW-UP: Specify the exact SPC chart type (P-chart/I-MR/X-bar-R), UCL/LCL calculation, monitoring frequency, alert threshold, responsible role, and reaction plan. Include control plan summary and next A3 review date.",
  "actions": [
    {"priority":"HIGH",  "action":"Specific action","tool":"Exact Lean/SS Tool"},
    {"priority":"HIGH",  "action":"Specific action","tool":"Exact Lean/SS Tool"},
    {"priority":"MEDIUM","action":"Specific action","tool":"Exact Lean/SS Tool"},
    {"priority":"LOW",   "action":"Specific action","tool":"Exact Lean/SS Tool"}
  ]
}

TOOL RULES:
- Quality      -> DPMO/Cp/Cpk, Pareto, Fishbone 5M, 5 Whys, Poka-Yoke, Standard Work, 5S, SPC P-chart, FMEA
- Maintenance  -> OEE(A*P*Q), MTBF/MTTR, Pareto, FMEA(RPN), TPM, SMED, I-MR chart
- Flow         -> Takt time, VSM, Line Balancing, Spaghetti, Kanban sizing, Heijunka, I-MR chart

Be specific, quantitative, and reference operator data directly in every section.
Write all narrative content in clear professional English. Keep each section \
focused (4-8 sentences). The JSON must be strictly valid and parseable."""


# ── Construction du message utilisateur selon le domaine ────────────────────
def _v(form: dict, key: str, default: Any) -> Any:
    val = form.get(key)
    return val if val not in (None, "") else default


def build_user_message(domain: str, form: dict) -> str:
    """Construit le prompt opérateur à partir des champs du formulaire."""
    if domain == "quality":
        return (
            "OPERATOR FORM — QUALITY\n"
            f"Date: {_v(form, 'date', '15/03/2026')} | Shift: {_v(form, 'shift', 'Morning')} "
            f"| Machine: {_v(form, 'machine', 'PL-03')}\n"
            f"Production target: {_v(form, 'target', 320)} units | "
            f"Actual: {_v(form, 'actual', 241)} units\n"
            f"Defects: {_v(form, 'defects', 28)} | Type: {_v(form, 'defectType', 'Surface scratches')}\n"
            f"Rework rate: {_v(form, 'rework', 8.7)}% | "
            f"Batch rejected: {_v(form, 'batchRej', 'Yes')}\n"
            f"Machine status: {_v(form, 'status', 'Degraded')} | "
            f"Days since last maintenance: {_v(form, 'daysMaint', 42)}\n"
            f"Observation: \"{_v(form, 'obs', 'Scratches after tool change. Coolant level was low. Same issue last week.')}\""
        )
    if domain == "maintenance":
        return (
            "OPERATOR FORM — MAINTENANCE\n"
            f"Date: {_v(form, 'date', '15/03/2026')} | Shift: {_v(form, 'shift', 'Morning')} "
            f"| Equipment: {_v(form, 'machine', 'Motor-L1')}\n"
            f"OEE Availability: {_v(form, 'oeeA', 71.4)}% | "
            f"Performance: {_v(form, 'oeeP', 79.2)}% | Quality: {_v(form, 'oeeQ', 74.2)}%\n"
            f"Downtime: {_v(form, 'downtime', 47)} min | "
            f"Failure type: {_v(form, 'failType', 'Bearing failure')}\n"
            f"Failure frequency this week: {_v(form, 'failFreq', 4)} | "
            f"Days since last maintenance: {_v(form, 'daysMaint', 42)}\n"
            f"Spare parts needed: {_v(form, 'spare', 'Bearing 6205-2RS')}\n"
            f"Observation: \"{_v(form, 'obs', 'Vibration increasing. Strange noise from motor. Production slowing.')}\""
        )
    # flow
    return (
        "OPERATOR FORM — FLOW\n"
        f"Date: {_v(form, 'date', '15/03/2026')} | Shift: {_v(form, 'shift', 'Morning')} "
        f"| Line: {_v(form, 'machine', 'Line A')}\n"
        f"Production target: {_v(form, 'target', 320)} | "
        f"Actual: {_v(form, 'actual', 241)} units\n"
        f"WIP: {_v(form, 'wip', 1240)} units | "
        f"Lead time: {_v(form, 'leadtime', 18.4)} days\n"
        f"Bottleneck: {_v(form, 'bottleneck', 'Assembly')} — "
        f"cycle time {_v(form, 'cycleTime', 168)}s vs Takt {_v(form, 'takt', 84)}s\n"
        f"On-time delivery: {_v(form, 'otd', 71.3)}%\n"
        f"Observation: \"{_v(form, 'obs', 'Assembly always behind. Parts piling up. Customers complaining.')}\""
    )


# ── Calcul KPI côté serveur (déterministe, indépendant du LLM) ───────────────
def compute_kpis(domain: str, form: dict) -> dict[str, Any]:
    """Calcule les KPI de base à partir du formulaire (affichage live + A3)."""
    def num(key, default):
        try:
            return float(form.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    kpis: dict[str, Any] = {}
    if domain == "quality":
        actual = num("actual", 241)
        defects = num("defects", 28)
        kpis["defect_rate"] = round((defects / actual) * 100, 1) if actual else 0.0
        kpis["dpmo"] = round((defects / actual) * 1_000_000) if actual else 0
        kpis["fpy"] = round((actual - defects) / actual * 100, 1) if actual else 0.0
    elif domain == "maintenance":
        a, p, q = num("oeeA", 71.4), num("oeeP", 79.2), num("oeeQ", 74.2)
        kpis["oee"] = round(a / 100 * p / 100 * q / 100 * 100, 1)
        kpis["availability"] = a
        kpis["performance"] = p
        kpis["quality"] = q
    else:  # flow
        tgt = num("target", 320)
        actual = num("actual", 241)
        kpis["wip"] = int(num("wip", 1240))
        kpis["lead_time"] = num("leadtime", 18.4)
        kpis["achievement"] = round(actual / tgt * 100, 1) if tgt else 0.0
        kpis["otd"] = num("otd", 71.3)
    return kpis


# ── Appel Claude avec retry exponentiel ─────────────────────────────────────
def _call_claude(client: anthropic.Anthropic, model: str, user_msg: str) -> str:
    delay = RETRY_DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Appel modèle %s (tentative %d/%d)", model, attempt, MAX_RETRIES)
            response = client.messages.create(
                model=model,
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return "".join(b.text for b in response.content if b.type == "text")
        except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
            is_last = attempt == MAX_RETRIES
            retriable = isinstance(exc, anthropic.RateLimitError) or (
                getattr(exc, "status_code", None) in (429, 503, 529)
            )
            if retriable and not is_last:
                logger.warning("Surcharge sur %s — attente %.0fs", model, delay)
                time.sleep(delay)
                delay *= RETRY_BACKOFF
            else:
                raise
    raise RuntimeError("retry épuisé")


def _safe_json_parse(raw: str) -> dict[str, Any]:
    """Nettoie et parse la réponse du modèle en JSON robuste."""
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    # Isole le premier objet JSON {...} si du texte parasite l'entoure.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


# ── Point d'entrée ───────────────────────────────────────────────────────────
def generate_a3(domain: str, form: dict, api_key: str) -> dict[str, Any]:
    """Génère un rapport A3. Retourne {ok, report|error, kpis}.

    Args:
        domain: "quality" | "maintenance" | "flow"
        form:   dict des champs du formulaire opérateur
        api_key: clé API Anthropic
    """
    if domain not in ("quality", "maintenance", "flow"):
        return {"ok": False, "error": f"Domaine inconnu : {domain}"}

    if not api_key or not api_key.strip():
        return {
            "ok": False,
            "error": "Clé API manquante. Configurez ANTHROPIC_API_KEY côté serveur.",
        }

    kpis = compute_kpis(domain, form)
    user_msg = build_user_message(domain, form)

    try:
        client = anthropic.Anthropic(api_key=api_key.strip())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Init client Anthropic impossible : {exc}"}

    last_error: Exception | None = None
    for model in CLAUDE_MODELS:
        try:
            raw = _call_claude(client, model, user_msg)
            report = _safe_json_parse(raw)
            report.setdefault("domain", domain.capitalize())
            return {"ok": True, "report": report, "kpis": kpis, "model": model}
        except anthropic.AuthenticationError:
            return {"ok": False, "error": "Clé API invalide ou non autorisée."}
        except anthropic.PermissionDeniedError:
            return {"ok": False, "error": "Accès refusé : modèle indisponible ou crédit épuisé."}
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning("JSON invalide sur %s : %s", model, exc)
            time.sleep(FALLBACK_PAUSE)
            continue
        except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
            last_error = exc
            logger.warning("Surcharge sur %s, bascule modèle suivant…", model)
            time.sleep(FALLBACK_PAUSE)
            continue
        except anthropic.APIConnectionError as exc:
            last_error = exc
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            break

    if isinstance(last_error, (anthropic.RateLimitError, anthropic.APIStatusError)):
        return {"ok": False, "error": "Surcharge ou limite de débit sur tous les modèles. Réessayez dans quelques minutes."}
    if isinstance(last_error, anthropic.APIConnectionError):
        return {"ok": False, "error": "Erreur de connexion. Vérifiez l'accès Internet du serveur."}
    if isinstance(last_error, json.JSONDecodeError):
        return {"ok": False, "error": "Le modèle n'a pas renvoyé un JSON valide. Réessayez."}
    return {"ok": False, "error": f"Erreur Anthropic : {last_error}"}
