"""Skicka Qt-meddelanden till den vanliga app- och felloggen."""
from __future__ import annotations
import logging
from core.plugin_base import PluginBase

_log = logging.getLogger("qt")
_handler = None  # Behåll callbacken vid liv under hela processen.


def install_qt_logging():
    global _handler
    if _handler is not None:
        return
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    def handler(message_type, context, message):
        try:
            _log.log(levels.get(message_type, logging.WARNING), "Qt: %s", message)
        except Exception:
            # Att logga Qt får aldrig krascha GUI:t.
            pass
    qInstallMessageHandler(handler)
    _handler = handler
    _log.info("Qt-loggning aktiverad")


class Plugin(PluginBase):
    NAME = "app_logging"
    DESCRIPTION = "Qt-loggning till central logg"
    DEPENDENCIES = []

    def initialize(self):
        install_qt_logging()
