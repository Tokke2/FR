"""Kontrollera GitHub-releaser vid start och hantera valfri OS-autostart."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from datetime import datetime

from core.autostart import AutostartManager
from core.no_console import gui_executable, hidden_kwargs, relaunch_arguments, spawn_detached
from core.plugin_base import PluginBase
from core.settings_manager import SettingsManager
from core import update_schedule
from .updater import changed_files, latest_archive, release_files

_log = logging.getLogger(__name__)
# Behåll pipen öppen ända till processens slut, även om pluginen avaktiveras.
_helpers: list[subprocess.Popen] = []


class Plugin(PluginBase):
    NAME = "auto_update"
    VERSION = "1.0.0"
    DESCRIPTION = "Releaseuppdatering och autostart"
    DEPENDENCIES = []

    def __init__(self, app):
        super().__init__(app)
        self.root = Path(__file__).resolve().parents[2]
        self.settings = None
        self.autostart = None
        self._menu_action = None
        self._update_action = None
        self._update_bridge = None
        self._window = None
        self._check_lock = threading.Lock()
        self._pending_helper = None
        # Daglig kontroll klockan 00:00 och automatisk omstart efter uppdatering.
        self._daily_timer = None
        self._last_check = None
        self._daily_action = None
        self._restart_action = None
        self._restart_pending = False

    def initialize(self):
        self.settings = SettingsManager(self.root / "settings.json")
        self.autostart = AutostartManager(settings=self.settings, base_dir=self.root)
        self.autostart.sync()

    def activate(self):
        self.is_active = True
        if getattr(sys, "frozen", False):
            _log.warning("Automatisk källkodsuppdatering stöds inte för paketerade körbara program")
        else:
            threading.Thread(target=self._check_for_updates, name="release-check", daemon=True).start()
        self._schedule_daily_check()
        # GUI:t skapas senare i aktiveringsordningen. Huvudtrådens Qt-timer
        # installerar menyalternativet när fönstret finns.
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            if QApplication.instance() is not None:
                QTimer.singleShot(0, lambda: self._install_menu(30))
        except ImportError:
            _log.debug("Ingen Qt-miljö för autostartmenyn")

    def _install_menu(self, remaining):
        from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QApplication, QMainWindow
        windows = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow)]
        if not windows:
            if remaining:
                QTimer.singleShot(500, lambda: self._install_menu(remaining - 1))
            else:
                _log.warning("Kunde inte lägga till autostartmeny: huvudfönstret saknas")
            return
        window = windows[0]
        self._window = window

        # Qt-objektet tar emot signaler på GUI-tråden, även när kontrollen
        # och nätverksanropen körs på en vanlig Python-bakgrundstråd.
        plugin = self
        class UpdateBridge(QObject):
            completed = Signal(str, str)

            def __init__(self, parent):
                super().__init__(parent)
                self.completed.connect(self.display_result)

            @Slot(str, str)
            def display_result(self, state, message):
                plugin._display_update_result(window, state, message)

        self._update_bridge = UpdateBridge(window)
        menu = window.menuBar().addMenu("Start och uppdatering")
        update_action = QAction("Sök efter uppdateringar", window)
        update_action.setToolTip("Jämför programmets filer med den senaste publicerade GitHub-releasen")
        update_action.triggered.connect(self._start_manual_check)
        menu.addAction(update_action)
        menu.addSeparator()
        toolbar = window.addToolBar("Uppdatering")
        toolbar.setObjectName("fordonsreg_update_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addAction(update_action)
        self._update_action = update_action
        if hasattr(window, "add_update_tray_action"):
            try:
                window.add_update_tray_action(update_action)
            except Exception:
                _log.exception("Kunde inte lägga till uppdatering i systemfältets meny")
        # Daglig kontroll och automatisk omstart kan stängas av, men är på
        # som standard enligt de hårda reglerna.
        menu.addSeparator()
        daily = QAction("Kontrollera uppdateringar varje dag klockan 00:00", window)
        daily.setCheckable(True)
        daily.setChecked(self._setting("update_daily_check", True))
        daily.toggled.connect(self._set_daily_check)
        menu.addAction(daily)
        restart = QAction("Starta om automatiskt efter uppdatering", window)
        restart.setCheckable(True)
        restart.setChecked(self._setting("update_restart", True))
        restart.toggled.connect(self._set_restart)
        menu.addAction(restart)
        menu.addSeparator()
        self._daily_action, self._restart_action = daily, restart

        action = QAction("Starta Fordonsreg vid inloggning", window)
        action.setCheckable(True)
        action.setChecked(self.autostart.is_enabled())
        action.toggled.connect(self._set_autostart)
        menu.addAction(action)
        if sys.platform.startswith(("win", "linux")):
            shortcut_action = QAction("Skapa Fordonsreg-genväg på skrivbordet", window)
            shortcut_action.triggered.connect(lambda: self._create_shortcut(window))
            menu.addAction(shortcut_action)
        self._menu_action = action

    # ── Inställningar för daglig kontroll och omstart ──────────────────
    def _setting(self, key, default=True):
        try:
            value = self.settings.get(key, default)
        except Exception:
            return default
        return default if value is None else bool(value)

    def _set_daily_check(self, enabled):
        try:
            self.settings.set("update_daily_check", bool(enabled))
            self.settings.save()
        except Exception:
            _log.exception("Kunde inte spara inställningen för daglig kontroll")
        self._schedule_daily_check()

    def _set_restart(self, enabled):
        try:
            self.settings.set("update_restart", bool(enabled))
            self.settings.save()
        except Exception:
            _log.exception("Kunde inte spara inställningen för automatisk omstart")

    def _schedule_daily_check(self):
        """Starta timern mot nästa midnatt. Ingen Qt betyder ingen timer."""
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
        except ImportError:
            return
        if QApplication.instance() is None:
            return
        if not self._setting("update_daily_check", True):
            if self._daily_timer is not None:
                self._daily_timer.stop()
            return
        if self._daily_timer is None:
            self._daily_timer = QTimer()
            self._daily_timer.setSingleShot(True)
            self._daily_timer.timeout.connect(self._daily_check_due)
        delay = update_schedule.milliseconds_until()
        self._daily_timer.start(delay)
        _log.info("Nästa automatiska uppdateringskontroll om %.1f timmar", delay / 3_600_000)

    def _daily_check_due(self):
        """Kör kontrollen vid midnatt och lägg upp nästa dygn."""
        if not self._setting("update_daily_check", True):
            return
        if update_schedule.is_due(self._last_check):
            _log.info("Daglig uppdateringskontroll klockan 00:00")
            self._last_check = datetime.now()
            threading.Thread(target=self._check_for_updates, name="daily-release-check",
                             daemon=True).start()
        self._schedule_daily_check()

    def _create_shortcut(self, window):
        from PySide6.QtWidgets import QMessageBox
        from core.desktop_shortcut import create_desktop_shortcut
        answer = QMessageBox.question(
            window, "Skapa genväg",
            "Skapa en Fordonsreg-genväg med programmets ikon på skrivbordet? "
            "En befintlig genväg skrivs inte över.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path = create_desktop_shortcut(self.root)
            _log.info("Skrivbordsgenväg skapad: %s", path)
            QMessageBox.information(window, "Genväg skapad", f"Genvägen skapades:\n{path}")
        except Exception as exc:
            _log.exception("Kunde inte skapa skrivbordsgenväg")
            QMessageBox.warning(window, "Genvägen kunde inte skapas", str(exc))

    def _set_autostart(self, enabled):
        success = self.autostart.set_enabled(enabled)
        actual = self.autostart.is_enabled()
        if not success or actual != enabled:
            from PySide6.QtWidgets import QMessageBox
            self._menu_action.blockSignals(True)
            self._menu_action.setChecked(actual)
            self._menu_action.blockSignals(False)
            QMessageBox.warning(None, "Autostart", "Kunde inte ändra autostart. Kontrollera behörigheter och loggar.")

    def _start_manual_check(self, *_):
        """Starta en kontroll utan att blockera gränssnittet."""
        if self._window is not None:
            # Ett val från systemfältet måste ge ett synligt fönster där
            # resultat och eventuella fel kan visas.
            try:
                self._window._show_from_tray()
            except (AttributeError, RuntimeError):
                pass
        if self._update_action is not None:
            self._update_action.setEnabled(False)
        threading.Thread(target=self._check_for_updates, kwargs={"interactive": True},
                         name="manual-release-check", daemon=True).start()

    def _display_update_result(self, window, state, message):
        from PySide6.QtWidgets import QMessageBox
        if self._update_action is not None:
            self._update_action.setEnabled(True)
        if state == "prepared" and self._setting("update_restart", True):
            self._restart_pending = True
        if state == "error":
            QMessageBox.warning(window, "Uppdatering misslyckades", message)
        else:
            QMessageBox.information(window, "Uppdatering", message)

    def _check_for_updates(self, interactive=False):
        """Jämför releasefiler; högst en kontroll/installationshjälpare åt gången."""
        if not self._check_lock.acquire(blocking=False):
            result = ("busy", "En uppdateringskontroll pågår redan. Försök igen om en stund.")
        else:
            try:
                result = self._check_for_updates_locked()
            except Exception as exc:
                _log.exception("Kunde inte kontrollera GitHub-release; appen fortsätter normalt")
                result = ("error", f"Kunde inte kontrollera uppdateringar: {exc}\n\nKontrollera internetanslutningen och loggarna.")
            finally:
                self._check_lock.release()
        if interactive and self._update_bridge is not None:
            try:
                self._update_bridge.completed.emit(*result)
            except RuntimeError:
                # Fönstret kan ha stängts medan nätverkskontrollen pågick.
                _log.debug("Uppdateringsfönstret stängdes före kontrollens slut")
        return result

    def _check_for_updates_locked(self):
        if getattr(sys, "frozen", False):
            return ("error", "Automatisk uppdatering stöds inte för en paketerad exe eller app-bundle.")
        # En omstart som väntar ska inte kunna starta en ny nedladdning.
        if self._restart_pending:
            return ("pending", "Uppdateringen installeras när programmet avslutas och "
                               "programmet startar sedan om automatiskt.")
        if self._pending_helper is not None and self._pending_helper.poll() is None:
            return ("pending", "En uppdatering är redan förberedd. Välj Avsluta Fordonsreg i menyn eller systemfältet, vänta några sekunder och starta igen. Kontrollera därefter på nytt om det kommit ytterligare ändringar.")
        self._pending_helper = None
        archive_path = None
        try:
            archive = latest_archive()
            if archive is None:
                _log.info("Ingen publicerad GitHub-release finns")
                return ("no_release", "Ingen publicerad stabil release finns på GitHub ännu.")
            files = release_files(archive)
            changes = changed_files(self.root, files)
            if not changes:
                _log.info("Programfilerna matchar senaste releasen")
                return ("current", "Programfilerna matchar den senaste publicerade releasen.")
            staging = self.root / ".update-staging"
            if staging.is_symlink():
                raise RuntimeError("Uppdateringskatalogen får inte vara en symbolisk länk")
            staging.mkdir(exist_ok=True)
            fd, name = tempfile.mkstemp(prefix="release-", suffix=".zip", dir=staging)
            archive_path = Path(name)
            with os.fdopen(fd, "wb") as out:
                out.write(archive)
                out.flush()
                os.fsync(out.fileno())
            worker = Path(__file__).with_name("worker.py")
            # pythonw.exe + dold process: annars blinkar ett terminalfönster
            # till när uppdateringen förbereds.
            helper = subprocess.Popen(
                [gui_executable(), str(worker), str(self.root), str(archive_path)],
                cwd=str(self.root), stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **hidden_kwargs(),
            )
            _helpers.append(helper)
            self._pending_helper = helper
            archive_path = None  # Hjälpprocessen äger arkivet.
            _log.info("%d ändrade filer installeras automatiskt när appen avslutas; gäller från nästa start", len(changes))
            return ("prepared", f"{len(changes)} ändrade programfiler är klara att installeras. Välj Avsluta Fordonsreg i menyn eller systemfältet, vänta några sekunder och starta igen. De gamla filerna säkerhetskopieras först.")
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)

    def restart_after_update(self) -> bool:
        """Starta om appen utan terminalfönster när en uppdatering väntar.

        Anropas av huvudfönstret precis före avslut. Returnerar True om en ny
        process startades. Själva installationen görs av hjälpprocessen när
        appens pipe stängs, så omstarten sker först efter att den är klar.
        """
        if not self._restart_pending or not self._setting("update_restart", True):
            return False
        entry = Path(sys.argv[0]) if sys.argv and sys.argv[0] else self.root / "main.pyw"
        if Path(entry).suffix not in (".py", ".pyw"):
            entry = self.root / "main.pyw"
        try:
            arguments = relaunch_arguments(str(entry), [])
            spawn_detached(arguments, self.root)
            _log.info("Programmet startas om automatiskt efter uppdateringen")
            self._restart_pending = False
            return True
        except Exception:
            _log.exception("Automatisk omstart kunde inte startas")
            return False

    def deactivate(self):
        self.is_active = False
