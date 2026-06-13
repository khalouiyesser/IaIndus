"""
config.py — Configuration centralisée du DSL Agent.

- Charge les variables d'environnement depuis `.env` (sans dépendance externe)
  puis depuis l'environnement système.
- Expose la clé API Anthropic et les paramètres de génération.
- Centralise les constantes (modèles, retry) pour éviter leur dispersion.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Chemins du projet ───────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

# ── Clé API ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

# ── Modèles Claude (ordre de priorité : fallback automatique) ───────────────
# Le premier modèle est l'objectif principal ; les suivants servent de repli
# en cas de surcharge ou de limite de débit (HTTP 429 / overloaded).
CLAUDE_MODELS: tuple[str, ...] = (
    "claude-sonnet-4-6",   # Principal : équilibré, rapide
    "claude-haiku-4-5",    # Repli : léger et économique
)
DEFAULT_MODEL = CLAUDE_MODELS[0]

# ── Paramètres de génération ────────────────────────────────────────────────
MAX_OUTPUT_TOKENS = 4096
TEMPERATURE = 0.2

# ── Paramètres de robustesse (retry) ────────────────────────────────────────
MAX_RETRIES = 3          # Tentatives max par modèle
RETRY_DELAY = 8.0        # Délai de base entre tentatives (secondes)
RETRY_BACKOFF = 1.5      # Multiplicateur exponentiel du délai
FALLBACK_PAUSE = 2.0     # Pause avant de basculer sur le modèle suivant

# ── Lien console pour obtenir une clé ───────────────────────────────────────
API_KEY_CONSOLE_URL = "https://console.anthropic.com/settings/keys"


def load_env_file(env_path: Path = ENV_FILE) -> None:
    """Charge les variables d'un fichier `.env` dans ``os.environ``.

    Les variables déjà présentes dans l'environnement ne sont pas écrasées,
    ce qui permet de surcharger le `.env` via l'environnement système (utile
    en hébergement : Render injecte la clé en variable d'environnement).
    """
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def get_anthropic_key() -> str:
    """Retourne la clé API Anthropic depuis le `.env` ou l'environnement."""
    load_env_file()
    return os.environ.get(ANTHROPIC_API_KEY_ENV, "").strip()


def has_api_key() -> bool:
    """Indique si une clé API non vide est disponible."""
    return bool(get_anthropic_key())
