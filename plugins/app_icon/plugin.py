"""Sätt samma programikon för Qt-applikationen och dess fönster."""
from __future__ import annotations

import logging
from pathlib import Path

from core.plugin_base import PluginBase

_log = logging.getLogger(__name__)


def set_application_icon(root: Path | None = None) -> bool:
    """Sätt Qt:s standardikon före huvudfönster och dialoger skapas.

    Alla Qt-fönster som inte uttryckligen tilldelas en egen fönsterikon
    ärver denna. Meddelandens info-/varningssymboler påverkas inte.
    """
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        _log.info("Ingen Qt-miljö; programikon behövs inte")
        return False

    application = QApplication.instance()
    if application is None:
        _log.info("Ingen QApplication; programikonen kan inte sättas")
        return False

    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    icon = QIcon()
    for size in (16, 32, 64, 256):
        path = root / f"ikon_{size}.png"
        if path.is_file():
            icon.addFile(str(path), QSize(size, size))
    fallback = root / "ikon.ico"
    if fallback.is_file():
        icon.addFile(str(fallback))
    if icon.isNull():
        _log.warning("Ingen läsbar programikon hittades i %s", root)
        return False
    application.setWindowIcon(icon)
    _log.info("Gemensam programikon aktiverad")
    return True


class Plugin(PluginBase):
    NAME = "app_icon"
    DESCRIPTION = "Gemensam programikon för fönster och dialoger"
    VERSION = "1.0.0"
    DEPENDENCIES = []

    def initialize(self):
        set_application_icon()
