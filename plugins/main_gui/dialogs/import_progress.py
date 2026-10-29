# -*- coding: utf-8 -*-
# Fil: plugins/main_gui/dialogs/import_progress.py

"""
Import Progress Dialog v1.0.1 — PySide6-port av inklistrad tkinter-version

Progress-dialog för långvariga operationer med detaljerad feedback:
determinate/indeterminate-läge, fas-indikator, tidsberäkning
(förfluten/uppskattad), färgkodad loggvy, avbryt-funktion och
felvisning. Trådsäker: alla uppdateringar skickas via en
queue.Queue och processas i UI-tråden av en QTimer (50 ms).

INNEHÅLL:
  - ProgressState         — dataclass (ren Python)
  - ImportProgressDialog  — QDialog med progress/logg/avbryt
  - ProgressContext       — context manager (with-syntax)
  - run_with_progress     — kör arbete i bakgrundstråd med dialog

ANVÄNDNING (från main_gui/plugin.py, framtida inkoppling):
    from .dialogs.import_progress import (
        ProgressContext, run_with_progress,
    )
    with ProgressContext(parent, "Importerar...", total=100) as p:
        for i, item in enumerate(items):
            if p.cancelled:
                break
            p.update_progress(f"Bearbetar {item}", current=i + 1)
    run_with_progress(parent, "Importerar...", work_func, total=100)

FÖRÄNDRINGAR v1.0.1 (granskad — spec v1.6 förbättringsregeln + KRAV 82):
  - FIX (korrekthet, KRITISK): tkinter → PySide6-port. main_gui är
    ett PySide6-plugin — tk.Toplevel/ttk kan inte köras. Portade
    widgets: QProgressBar (indeterminate = setRange(0, 0) busy-läge,
    ingen start()-loop), QPlainTextEdit (read-only logg med
    QTextCharFormat-färger i stället för tk.Text + tag_configure),
    QLabel/QGroupBox/QPushButton, QVBoxLayout/QHBoxLayout.
    self.after(50, ...) → QTimer; WM_DELETE_WINDOW → closeEvent().
  - FIX (trådsäkerhet): increment() räknade self._state.current i
    ANROPARENS tråd (race vid flera trådar) — nu skickas
    'increment'-action i kön och räkningen sker i UI-tråden.
  - FIX (stabilitet): tysta "except Exception: pass" → _log.exception
    (lazy %s); loggvyn skyddad med setMaximumBlockCount(5000)
    (oändlig logg → minnesväxt); on_complete/on_error-callbacks
    try/except-skyddade; QTimer stoppas i close().
  - FIX (låsta regler): modul-nivå _log (aldrig print); VERSION/
    AUTHOR (Rickard Längkvist) + dynamisk copyright; setObjectName
    med design-tokens (PageTitle, StatusLabel, DialogIcon,
    SecondaryButton, progressBar, logGroup, logText); full-form
    PySide6-enums (Qt.WindowModality.WindowModal,
    QTextCursor.MoveOperation.End); "# Fil:"-kommentar behållen
    (KRAV 58); self.parent-attributet BORT (skuggar QObject.parent()
    i PySide6) → parentWidget()/privat _parent.
  - FIX (UI/UX): dialogen visas icke-blockerande (show() +
    WindowModal) — samma beteende som tkinter grab_set() men utan
    att blockera; centrering över parent via frameGeometry().
  - OBS: logg-färgerna är semantiska signal-färger som namngivna
    konstanter (_LOG_COLORS) — samma mönster som STRENGTH_COLORS i
    password_dialog.py och Styles-klasserna i kodbasen. Bakgrund
    ärver temats palett (ingen hårdkodad bg).
FÖRÄNDRINGAR v1.0.0:
  - NY FIL (inklistrad original): tkinter-version (ersatt av v1.0.1).
Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_log: logging.Logger = logging.getLogger("import_progress")

VERSION: str = "1.0.1"
AUTHOR: str = "Rickard Längkvist"

# Semantiska signal-färger för loggnivåer (mönster: STRENGTH_COLORS).
_LOG_COLORS: Dict[str, str] = {
    "info": "#4fc3f7",
    "success": "#81c784",
    "warning": "#ffb74d",
    "error": "#e57373",
    "timestamp": "#808080",
}

_QUEUE_POLL_INTERVAL_MS: int = 50
_MAX_LOG_BLOCKS: int = 5000


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# DATAKLASSER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProgressState:
    """Tillstånd för progress (uppdateras i UI-tråden via kön)."""

    current: int = 0
    total: int = 0
    message: str = ""
    sub_message: str = ""
    phase: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100)

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def estimated_remaining(self) -> Optional[float]:
        if self.current <= 0 or self.total <= 0:
            return None
        elapsed = self.elapsed_seconds
        rate = self.current / elapsed if elapsed > 0 else 0
        remaining = self.total - self.current
        return remaining / rate if rate > 0 else None


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ImportProgressDialog(QDialog):
    """
    Progress-dialog för långvariga operationer (trådsäker).

    Features:
    - Determinate och indeterminate läge
    - Fas-indikator
    - Tidsberäkning (förfluten/uppskattad)
    - Loggvy för meddelanden (färgkodad)
    - Avbryt-funktion
    - Felvisning
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "Bearbetar...",
        total: int = 0,
        show_log: bool = True,
        show_cancel: bool = True,
        cancellable: bool = True,
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._show_log = show_log
        self._show_cancel = show_cancel
        self._cancellable = cancellable
        self._on_cancel = on_cancel

        self._state = ProgressState(total=total)
        self._cancelled = False
        self._closed = False
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._log_text: Optional[QPlainTextEdit] = None
        self._cancel_button: Optional[QPushButton] = None

        self.setObjectName("importProgressDialog")
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        if show_log:
            self.resize(520, 400)
            self.setMinimumSize(400, 300)
        else:
            self.resize(460, 170)
            self.setMinimumSize(360, 130)

        self._create_widgets()
        self._center_over_parent()

        self._state.started_at = datetime.now()

        self._timer = QTimer(self)
        self._timer.setInterval(_QUEUE_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._process_queue)
        self._timer.start()

        self.show()

    def _create_widgets(self) -> None:
        """Bygg dialogens widgets (design-tokens)."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)

        header = QHBoxLayout()
        self._icon_label = QLabel("⏳", self)
        self._icon_label.setObjectName("DialogIcon")
        header.addWidget(self._icon_label)
        title_box = QVBoxLayout()
        self._title_label = QLabel(self._title, self)
        self._title_label.setObjectName("PageTitle")
        title_box.addWidget(self._title_label)
        self._phase_label = QLabel("", self)
        self._phase_label.setObjectName("StatusLabel")
        title_box.addWidget(self._phase_label)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        self._mode = "indeterminate" if self._state.total <= 0 else "determinate"
        self._progress = QProgressBar(self)
        self._progress.setObjectName("progressBar")
        if self._mode == "indeterminate":
            self._progress.setRange(0, 0)  # busy-läge (animeras av Qt)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
        layout.addWidget(self._progress)

        status = QHBoxLayout()
        self._message_label = QLabel("Startar...", self)
        self._message_label.setObjectName("StatusLabel")
        status.addWidget(self._message_label, 1)
        self._stats_label = QLabel("", self)
        self._stats_label.setObjectName("StatusLabel")
        status.addWidget(self._stats_label)
        layout.addLayout(status)

        self._detail_label = QLabel("", self)
        self._detail_label.setObjectName("StatusLabel")
        layout.addWidget(self._detail_label)

        if self._show_log:
            log_group = QGroupBox("Logg", self)
            log_group.setObjectName("logGroup")
            log_layout = QVBoxLayout(log_group)
            self._log_text = QPlainTextEdit(log_group)
            self._log_text.setObjectName("logText")
            self._log_text.setReadOnly(True)
            self._log_text.setMaximumBlockCount(_MAX_LOG_BLOCKS)
            log_layout.addWidget(self._log_text)
            layout.addWidget(log_group, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        if self._show_cancel and self._cancellable:
            self._cancel_button = QPushButton("Avbryt", self)
            self._cancel_button.setObjectName("SecondaryButton")
            self._cancel_button.clicked.connect(self._on_cancel_click)
            button_row.addWidget(self._cancel_button)
        layout.addLayout(button_row)

    def _center_over_parent(self) -> None:
        """Centrera dialogen över föräldra-widgeten (om synlig)."""
        parent = self.parentWidget()
        if parent is None or not parent.isVisible():
            return
        self.adjustSize()
        geometry = self.frameGeometry()
        geometry.moveCenter(parent.geometry().center())
        self.move(geometry.topLeft())

    def _start_queue_processor(self) -> None:
        """Starta bakgrundsprocessor för meddelanden (QTimer-pump)."""
        self._process_queue()

    def _process_queue(self) -> None:
        """Processa meddelandekön (körs i UI-tråden via QTimer)."""
        if self._closed:
            return
        try:
            while True:
                try:
                    msg = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_queue_message(msg)
                except Exception:
                    _log.exception("Fel vid hantering av kömeddelande.")
        except Exception:
            _log.exception("Fel vid processning av meddelandekön.")

    def _handle_queue_message(self, msg: Dict[str, Any]) -> None:
        """Hantera ett meddelande från kön."""
        action = msg.get("action")
        if action == "update":
            self._do_update(**msg.get("kwargs", {}))
        elif action == "increment":
            # Räkningen sker här i UI-tråden (trådsäker).
            self._state.current += 1
            self._do_update(
                message=msg.get("message", ""),
                current=self._state.current,
            )
        elif action == "log":
            self._do_log(msg.get("message", ""), msg.get("level", "info"))
        elif action == "complete":
            self._do_complete(**msg.get("kwargs", {}))
        elif action == "error":
            self._do_error(msg.get("message", ""))

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC API (trådsäker — alla skickar via kön)
    # ══════════════════════════════════════════════════════════════════════════

    def update_progress(
        self,
        message: str = "",
        current: Optional[int] = None,
        total: Optional[int] = None,
        phase: Optional[str] = None,
        sub_message: str = "",
    ) -> None:
        """
        Uppdatera progress (thread-safe).

        Args:
            message: Huvudmeddelande
            current: Aktuellt steg
            total: Totalt antal steg
            phase: Fasbeskrivning (t.ex. "Steg 1/3")
            sub_message: Undermeddelande
        """
        self._queue.put({
            "action": "update",
            "kwargs": {
                "message": message,
                "current": current,
                "total": total,
                "phase": phase,
                "sub_message": sub_message,
            },
        })

    def log(self, message: str, level: str = "info") -> None:
        """
        Logga meddelande (thread-safe).

        Args:
            message: Meddelande att logga
            level: info, success, warning, error
        """
        self._queue.put({
            "action": "log",
            "message": message,
            "level": level,
        })

    def log_info(self, message: str) -> None:
        """Logga info-meddelande."""
        self.log(message, "info")

    def log_success(self, message: str) -> None:
        """Logga success-meddelande."""
        self.log(message, "success")

    def log_warning(self, message: str) -> None:
        """Logga varning (state.warnings uppdateras i UI-tråden)."""
        self.log(message, "warning")

    def log_error(self, message: str) -> None:
        """Logga fel (state.errors uppdateras i UI-tråden)."""
        self.log(message, "error")

    def set_phase(self, phase: str) -> None:
        """Sätt aktuell fas."""
        self.update_progress(phase=phase)

    def increment(self, message: str = "") -> None:
        """Öka progress med ett steg (räknas i UI-tråden)."""
        self._queue.put({
            "action": "increment",
            "message": message,
        })

    def complete(
        self,
        message: str = "Klar!",
        auto_close: bool = False,
        auto_close_delay: int = 2000,
    ) -> None:
        """
        Markera som klar.

        Args:
            message: Slutmeddelande
            auto_close: Stäng automatiskt
            auto_close_delay: Fördröjning innan stängning (ms)
        """
        self._queue.put({
            "action": "complete",
            "kwargs": {
                "message": message,
                "auto_close": auto_close,
                "auto_close_delay": auto_close_delay,
            },
        })

    def error(self, message: str) -> None:
        """Markera som fel."""
        self._queue.put({
            "action": "error",
            "message": message,
        })

    def close(self) -> None:
        """Stäng dialogen (tömmer kö, stoppar timer, gömmer + städar)."""
        if self._closed:
            return
        # Töm kvarvarande kömeddelanden (dataförlust-skydd — meddelanden
        # precis före stängning ska inte gå förlorade).
        try:
            self._process_queue()
        except Exception:
            _log.exception("Fel vid tömning av kö vid stängning.")
        self._closed = True
        self._state.completed_at = datetime.now()
        try:
            self._timer.stop()
            self.hide()
            self.deleteLater()
        except Exception:
            _log.exception("Fel vid stängning av progress-dialog.")

    @property
    def cancelled(self) -> bool:
        """Kolla om avbruten."""
        return self._cancelled

    @property
    def state(self) -> ProgressState:
        """Hämta state."""
        return self._state

    # ══════════════════════════════════════════════════════════════════════════
    # PRIVATA METODER (körs i UI-tråden)
    # ══════════════════════════════════════════════════════════════════════════

    def _do_update(
        self,
        message: str = "",
        current: Optional[int] = None,
        total: Optional[int] = None,
        phase: Optional[str] = None,
        sub_message: str = "",
    ) -> None:
        """Utför uppdatering i UI-tråden."""
        if self._closed:
            return

        if message:
            self._state.message = message
        if sub_message:
            self._state.sub_message = sub_message
        if phase:
            self._state.phase = phase
        if current is not None:
            self._state.current = current
        if total is not None:
            self._state.total = total
            if total > 0 and self._mode == "indeterminate":
                self._progress.setRange(0, 100)
                self._progress.setValue(0)
                self._mode = "determinate"

        self._update_ui()

    def _do_log(self, message: str, level: str) -> None:
        """Logga meddelande i UI-tråden (färgkodat, tidsstämplat)."""
        if self._closed:
            return

        # Registrera i state EXAKT en gång (i UI-tråden — trådsäkert).
        if level == "warning":
            self._state.warnings.append(message)
        elif level == "error":
            self._state.errors.append(message)

        if self._log_text is None:
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
        }
        icon = icons.get(level, "ℹ️")
        color = _LOG_COLORS.get(level, _LOG_COLORS["info"])
        stamp_color = _LOG_COLORS["timestamp"]

        self._append_colored("[%s] " % timestamp, stamp_color)
        self._append_colored("%s %s\n" % (icon, message), color)

    def _append_colored(self, text: str, color: str) -> None:
        """Lägg till text med färg i loggvyn (end of document)."""
        if self._log_text is None:
            return
        cursor = self._log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(QColor(color)))
        cursor.insertText(text, fmt)
        self._log_text.setTextCursor(cursor)
        self._log_text.ensureCursorVisible()

    def _do_complete(
        self,
        message: str = "Klar!",
        auto_close: bool = False,
        auto_close_delay: int = 2000,
    ) -> None:
        """Hantera completion."""
        if self._closed:
            return

        self._state.completed_at = datetime.now()
        self._state.message = message
        self._state.current = self._state.total

        self._icon_label.setText("✅")
        self._title_label.setText("Klar!")

        if self._mode == "indeterminate":
            self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._message_label.setText(message)

        elapsed = self._state.elapsed_seconds
        self._stats_label.setText(
            "Tid: %s" % self._format_time(elapsed)
        )

        if self._cancel_button is not None:
            self._cancel_button.setText("Stäng")
            self._cancel_button.clicked.disconnect()
            self._cancel_button.clicked.connect(self.close)

        if self._log_text is not None:
            self.log_success(
                "%s (Tid: %s)" % (message, self._format_time(elapsed))
            )
            if self._state.warnings:
                self.log_warning(
                    "%d varningar" % len(self._state.warnings)
                )
            if self._state.errors:
                self.log_error("%d fel" % len(self._state.errors))

        if auto_close:
            QTimer.singleShot(auto_close_delay, self.close)

    def _do_error(self, message: str) -> None:
        """Hantera fel."""
        if self._closed:
            return

        # state.errors registreras via self.log → _do_log (en gång,
        # även utan loggvy — _do_log registrerar före vy-checken).
        self._icon_label.setText("❌")
        self._title_label.setText("Fel!")

        if self._mode == "indeterminate":
            self._progress.setRange(0, 100)

        self._message_label.setText(message)
        self._message_label.setStyleSheet(
            "color: %s;"
            % _LOG_COLORS["error"]
        )

        if self._cancel_button is not None:
            self._cancel_button.setText("Stäng")
            self._cancel_button.clicked.disconnect()
            self._cancel_button.clicked.connect(self.close)

        self.log(message, "error")

    def _update_ui(self) -> None:
        """Uppdatera alla UI-element."""
        if self._closed:
            return

        msg = self._state.message
        if len(msg) > 60:
            msg = msg[:57] + "..."
        self._message_label.setText(msg)

        if self._state.phase:
            self._phase_label.setText(self._state.phase)

        if self._mode == "determinate" and self._state.total > 0:
            self._progress.setValue(int(self._state.percent))

        stats_parts: List[str] = []
        if self._state.total > 0:
            stats_parts.append("%.0f%%" % self._state.percent)

        elapsed = self._state.elapsed_seconds
        if elapsed > 0:
            stats_parts.append("⏱️ %s" % self._format_time(elapsed))

        remaining = self._state.estimated_remaining
        if remaining is not None and remaining > 0:
            stats_parts.append("⏳ ~%s" % self._format_time(remaining))

        self._stats_label.setText(" | ".join(stats_parts))

        if self._state.total > 0:
            self._detail_label.setText(
                "%d / %d" % (self._state.current, self._state.total)
            )

        QApplication.processEvents()

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Formatera tid (s, m s, h m)."""
        if seconds < 60:
            return "%.0fs" % seconds
        if seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return "%dm %ds" % (mins, secs)
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return "%dh %dm" % (hours, mins)

    def _on_cancel_click(self) -> None:
        """Hantera avbryt-klick."""
        self._cancelled = True
        self._icon_label.setText("⏹️")
        self._message_label.setText("Avbryter...")

        _log.info("Progress-dialog avbruten av användaren.")
        if self._log_text is not None:
            self.log_warning("Avbruten av användaren")

        if self._on_cancel is not None:
            try:
                self._on_cancel()
            except Exception:
                _log.exception("on_cancel-callback misslyckades.")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Hantera fönsterstängning (avbryt om avbrytbar)."""
        if self._cancellable and not self._cancelled and not self._closed:
            self._on_cancel_click()
        if not self._closed:
            self.close()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class ProgressContext:
    """
    Context manager för progress-dialog.

    Användning:
        with ProgressContext(parent, "Importerar...", total=100) as progress:
            for i, item in enumerate(items):
                if progress.cancelled:
                    break
                progress.update_progress(
                    "Bearbetar %s" % item,
                    current=i + 1,
                )
                process(item)
            progress.complete("Färdig!")
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        total: int = 0,
        **kwargs: Any,
    ) -> None:
        self._parent = parent
        self._title = title
        self._total = total
        self._kwargs = kwargs
        self.dialog: Optional[ImportProgressDialog] = None

    def __enter__(self) -> ImportProgressDialog:
        self.dialog = ImportProgressDialog(
            self._parent,
            self._title,
            total=self._total,
            **self._kwargs,
        )
        return self.dialog

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self.dialog is not None:
            if exc_type is not None:
                self.dialog.error("Fel: %s" % exc_val)
            self.dialog.close()
        return False


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def run_with_progress(
    parent: Optional[QWidget],
    title: str,
    work_func: Callable[[ImportProgressDialog], Any],
    on_complete: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
    total: int = 0,
    **dialog_kwargs: Any,
) -> None:
    """
    Kör funktion med progress-dialog i bakgrundstråd.

    Args:
        parent: Föräldra-widget
        title: Dialogtitel
        work_func: Funktion att köra (tar progress som argument)
        on_complete: Callback när klar (får resultat)
        on_error: Callback vid fel (får exception)
        total: Totalt antal steg
        **dialog_kwargs: Extra argument till dialogen

    Användning:
        def import_data(progress):
            for i, row in enumerate(data):
                if progress.cancelled:
                    return None
                progress.update_progress(
                    "Rad %d" % i,
                    current=i + 1,
                )
                process(row)
            return {"imported": len(data)}

        run_with_progress(
            parent,
            "Importerar...",
            import_data,
            on_complete=lambda r: print("Klart: %s" % r),
            total=len(data),
        )
    """
    dialog = ImportProgressDialog(
        parent,
        title,
        total=total,
        **dialog_kwargs,
    )

    result: Any = None
    error: Optional[BaseException] = None

    def worker() -> None:
        nonlocal result, error
        try:
            result = work_func(dialog)
        except Exception as exc:
            error = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def check_thread() -> None:
        if thread.is_alive():
            QTimer.singleShot(100, check_thread)
        else:
            if error is not None:
                dialog.error(str(error))
                if on_error is not None:
                    try:
                        on_error(error)
                    except Exception:
                        _log.exception("on_error-callback misslyckades.")
            else:
                dialog.complete("Klar!", auto_close=True)
                if on_complete is not None:
                    try:
                        on_complete(result)
                    except Exception:
                        _log.exception("on_complete-callback misslyckades.")

    QTimer.singleShot(100, check_thread)


__all__: List[str] = [
    "ProgressState",
    "ImportProgressDialog",
    "ProgressContext",
    "run_with_progress",
    "get_copyright_string",
    "VERSION",
    "AUTHOR",
]
