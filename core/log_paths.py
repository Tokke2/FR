"""Gemensam plats för Fordonsregs tekniska loggfiler."""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]


def app_log_dir(root: Path | None = None) -> Path:
    """Returnera undermappen logs i appmappen, oberoende av aktuell katalog."""
    return (Path(root).resolve() if root is not None else APP_ROOT) / "logs"
