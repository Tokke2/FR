# -*- coding: utf-8 -*-

# core/single_instance.py

"""
SingleInstance v1.0.0 — Singelinstanslås.

Transportstyrelsen Fordonsregistreringssystem.

ANSVAR:

    - Förhindra att fler än EN instans av applikationen körs

    - Plattformsspecifika lås:

        * Windows:     Named Mutex (via ctypes/kernel32) —
                       primär metod, fungerar även vid hård krasch
                       (OS släpper mutexen automatiskt)

        * Linux/macOS: fcntl.flock på låsfil — OS släpper låset
                       automatiskt vid processdöd

        * Fallback:    PID-fil med stale-detektering (om varken
                       mutex eller flock är tillgängliga)

    - Andra instansen -> focus_existing() signalerar befintlig
      instans att visa sitt fönster (via trigger-fil som
      huvudinstansen pollar / main_window kan watcha)

    - Cleanup garanteras vid normal exit (atexit), vid signaler
      (SIGINT/SIGTERM/SIGBREAK) och är ofarlig vid krasch
      (OS-låsen släpps av kerneln; stale PID-fil detekteras)

API (spec Sektion D):

    SingleInstance.acquire()        -> bool
    SingleInstance.release()        -> None
    SingleInstance.focus_existing() -> None

ANVÄNDNING (main.pyw):

    from core.single_instance import SingleInstance

    instance = SingleInstance("ts_fordonsreg")

    if not instance.acquire():
        instance.focus_existing()
        sys.exit(0)

    # ... starta appen ...
    # release() körs automatiskt via atexit, men kan kallas
    # explicit vid kontrollerad shutdown.

FOCUS-MEKANISM:

    Eftersom mutex/flock inte kan bära meddelanden används en
    enkel trigger-fil i temp-katalogen:

      1. Andra instansen skriver <lockname>.show (atomiskt)

      2. Huvudinstansen pollar via check_show_request()
         (anropas lämpligen från en QTimer i main_window,
         t.ex. var 1000:e ms) och visar fönstret + raderar filen

    Detta är plattformsoberoende, kraschsäkert och kräver inga
    extra beroenden.

KRASCHSÄKERHET:

    - ALLA publika metoder är kraschsäkra (fel loggas, appen
      kraschar aldrig p.g.a. låshantering)

    - Dubbel-release är ofarlig (idempotent)

    - Stale PID-fil (process död) detekteras och tas över

    - Signalhanterare kedjar vidare till ev. tidigare hanterare

KONSOLIDERAD (Session 10):

    - Hela filen omskriven ren: markdown-artefakter borttagna
      ([url]-länkar, **-markeringar, *x*-mönster, &gt;/&lt;/&amp; osv.).
    - Mangled kod återställd: self._pid_path.read_text(...) och
      lock_file.seek(0) (var splittrade av [url]-mönster → ogiltig
      Python), f".{path.name}.tmp_" (var f".{[path.name](...)}.tmp_").

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
Alla rättigheter förbehållna.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Final, Optional

_log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS

# ══════════════════════════════════════════════════════════════════════════════

VERSION: Final[str] = "1.0.0"
AUTHOR: Final[str] = "Rickard Längkvist"

DEFAULT_LOCK_NAME: Final[str] = "ts_fordonsregistreringssystem"
SHOW_TRIGGER_SUFFIX: Final[str] = ".show"
PID_SUFFIX: Final[str] = ".pid"
LOCK_SUFFIX: Final[str] = ".lock"

IS_WINDOWS: Final[bool] = sys.platform.startswith("win")

# Windows-konstanter (kernel32)
ERROR_ALREADY_EXISTS: Final[int] = 183


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return f"Copyright © {datetime.now().year} {AUTHOR}"


# ══════════════════════════════════════════════════════════════════════════════
# PLATTFORMSDETEKTERING (kraschsäker)

# ══════════════════════════════════════════════════════════════════════════════

_HAS_FCNTL = False
if not IS_WINDOWS:
    try:
        import fcntl  # noqa: F401
        _HAS_FCNTL = True
    except ImportError:
        _HAS_FCNTL = False

_HAS_CTYPES = False
if IS_WINDOWS:
    try:
        import ctypes  # noqa: F401
        _HAS_CTYPES = True
    except ImportError:
        _HAS_CTYPES = False


def _atomic_write_text(path: Path, content: str) -> None:
    """Skriv text atomiskt: mkstemp -> fdopen -> fsync -> os.replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f".{path.name}.tmp_",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _pid_is_running(pid: int) -> bool:
    """
    Kontrollera om en process med givet PID lever. KRASCHSÄKER.
    """

    if pid <= 0:
        return False

    if IS_WINDOWS:
        if not _HAS_CTYPES:
            return False
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                # Kontrollera att processen inte är avslutad
                exit_code = ctypes.c_ulong(0)
                STILL_ACTIVE = 259
                alive = False
                if kernel32.GetExitCodeProcess(
                    handle, ctypes.byref(exit_code)
                ):
                    alive = exit_code.value == STILL_ACTIVE
                kernel32.CloseHandle(handle)
                return alive
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Processen finns men ägs av annan användare
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE INSTANCE

# ══════════════════════════════════════════════════════════════════════════════


class SingleInstance:
    """
    Plattformsoberoende singelinstanslås.

    Låsstrategi (i prioritetsordning):
      1. Windows: Named Mutex (Global\\<name>_mutex)
      2. POSIX:   fcntl.flock på <tempdir>/<name>.lock
      3. Fallback: PID-fil med stale-detektering

    Trådsäker. Idempotent release. Cleanup via atexit + signaler.
    """

    def __init__(
        self,
        lock_name: str = DEFAULT_LOCK_NAME,
        *,
        lock_dir: Optional[Path] = None,
        on_show_request: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Initiera SingleInstance.

        Args:
            lock_name: Unikt namn för låset (per applikation)
            lock_dir: Katalog för låsfiler
                      (None = systemets temp-katalog)
            on_show_request: Callback som anropas av
                             check_show_request() när en andra
                             instans begärt fokus
        """

        self._lock_name = self._sanitize_name(lock_name)
        self._lock_dir = Path(lock_dir or tempfile.gettempdir())
        self._on_show_request = on_show_request

        self._lock = threading.RLock()
        self._acquired = False
        self._method: str = "none"  # mutex | flock | pidfile | none

        # Windows mutex-handle
        self._mutex_handle: Optional[int] = None

        # POSIX flock-fil
        self._flock_file: Optional[Any] = None

        # Filsökvägar
        self._lock_path = self._lock_dir / (
            self._lock_name + LOCK_SUFFIX
        )
        self._pid_path = self._lock_dir / (
            self._lock_name + PID_SUFFIX
        )
        self._show_path = self._lock_dir / (
            self._lock_name + SHOW_TRIGGER_SUFFIX
        )

        # Sparade ursprungliga signalhanterare (för kedjning)
        self._prev_handlers: Dict[int, Any] = {}
        self._cleanup_registered = False

    # ──────────────────────────────────────────────────────────────────
    # PUBLIKT API (spec-kontrakt)

    # ──────────────────────────────────────────────────────────────────

    def acquire(self) -> bool:
        """
        Försök ta singelinstanslåset. KRASCHSÄKER.

        Returns:
            True  = vi är första/enda instansen (lås taget)
            False = en annan instans kör redan
        """

        with self._lock:
            if self._acquired:
                return True

            try:
                if IS_WINDOWS and _HAS_CTYPES:
                    ok = self._acquire_windows_mutex()
                    if ok is not None:
                        if ok:
                            self._method = "mutex"
                            self._post_acquire()
                        return ok

                if _HAS_FCNTL:
                    ok = self._acquire_flock()
                    if ok is not None:
                        if ok:
                            self._method = "flock"
                            self._post_acquire()
                        return ok

                # Sista utväg: PID-fil
                ok = self._acquire_pidfile()
                if ok:
                    self._method = "pidfile"
                    self._post_acquire()
                return ok

            except Exception as exc:
                _log.error(
                    "Oväntat fel vid lås-förvärv: %s",
                    exc, exc_info=True,
                )
                # Hellre tillåta start än att blockera felaktigt
                return True

    def release(self) -> None:
        """
        Släpp låset. KRASCHSÄKER och IDEMPOTENT
        (dubbel-release är ofarlig).
        """

        with self._lock:
            if not self._acquired:
                return

            # Windows mutex
            if self._mutex_handle is not None:
                try:
                    import ctypes
                    ctypes.windll.kernel32.ReleaseMutex(
                        self._mutex_handle
                    )
                    ctypes.windll.kernel32.CloseHandle(
                        self._mutex_handle
                    )
                except Exception as exc:
                    _log.debug("Mutex-release fel: %s", exc)
                self._mutex_handle = None

            # POSIX flock
            if self._flock_file is not None:
                try:
                    import fcntl
                    fcntl.flock(
                        self._flock_file.fileno(), fcntl.LOCK_UN
                    )
                    self._flock_file.close()
                except Exception as exc:
                    _log.debug("flock-release fel: %s", exc)
                self._flock_file = None
                try:
                    self._lock_path.unlink(missing_ok=True)
                except Exception:
                    pass

            # PID-fil (tas alltid bort om den är vår)
            try:
                if self._pid_path.exists():
                    content = self._pid_path.read_text(
                        encoding="utf-8"
                    ).strip()
                    if content == str(os.getpid()):
                        self._pid_path.unlink()
            except Exception as exc:
                _log.debug("PID-fil-cleanup fel: %s", exc)

            # Show-trigger städas
            try:
                self._show_path.unlink(missing_ok=True)
            except Exception:
                pass

            self._acquired = False
            _log.info(
                "Singelinstanslås släppt (%s)", self._method,
            )
            self._method = "none"

    def focus_existing(self) -> None:
        """
        Signalera den redan körande instansen att visa sitt
        fönster. KRASCHSÄKER.

        Skriver en trigger-fil som huvudinstansen plockar upp via
        check_show_request() (pollas med QTimer i main_window).
        """

        try:
            payload = (
                f"{os.getpid()}\n"
                f"{datetime.now().isoformat(timespec='seconds')}\n"
            )
            _atomic_write_text(self._show_path, payload)
            _log.info(
                "Fokusbegäran skickad till befintlig instans "
                "(%s)",
                self._show_path,
            )
        except Exception as exc:
            _log.error(
                "Kunde inte signalera befintlig instans: %s", exc,
            )

    # ──────────────────────────────────────────────────────────────────
    # FOCUS-POLLING (anropas av huvudinstansen, t.ex. via QTimer)

    # ──────────────────────────────────────────────────────────────────

    def check_show_request(self) -> bool:
        """
        Kontrollera om en andra instans begärt fokus.
        Anropas periodiskt av huvudinstansen (QTimer ~1000 ms).
        Raderar trigger-filen och anropar on_show_request-callback.

        Returns:
            True om en fokusbegäran fanns
        """

        try:
            if not self._show_path.exists():
                return False

            try:
                self._show_path.unlink()
            except Exception:
                pass

            _log.info(
                "Fokusbegäran mottagen — visar huvudfönstret"
            )

            if self._on_show_request is not None:
                try:
                    self._on_show_request()
                except Exception:
                    _log.exception(
                        "on_show_request-callback misslyckades"
                    )

            return True

        except Exception as exc:
            _log.debug("check_show_request fel: %s", exc)
            return False

    def set_show_callback(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        """Sätt/byt callback för fokusbegäran (t.ex. show_window)."""

        self._on_show_request = callback

    # ──────────────────────────────────────────────────────────────────
    # PROPERTIES

    # ──────────────────────────────────────────────────────────────────

    @property

    def is_acquired(self) -> bool:
        """True om låset hålls av denna process."""

        return self._acquired

    @property

    def method(self) -> str:
        """Aktiv låsmetod: mutex | flock | pidfile | none."""

        return self._method

    # ──────────────────────────────────────────────────────────────────
    # INTERNA LÅSMETODER

    # ──────────────────────────────────────────────────────────────────

    def _acquire_windows_mutex(self) -> Optional[bool]:
        """
        Windows Named Mutex.

        Returns:
            True/False vid avgjort resultat,
            None om metoden inte kunde användas (-> nästa metod).
        """

        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32

            mutex_name = f"Global\\{self._lock_name}_mutex"
            handle = kernel32.CreateMutexW(None, False, mutex_name)

            if not handle:
                # Global\ kan kräva rättigheter — prova Local\
                mutex_name = f"Local\\{self._lock_name}_mutex"
                handle = kernel32.CreateMutexW(
                    None, False, mutex_name
                )
                if not handle:
                    _log.debug(
                        "CreateMutexW misslyckades — faller "
                        "tillbaka"
                    )
                    return None

            last_error = kernel32.GetLastError()
            if last_error == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(handle)
                _log.info(
                    "Annan instans kör redan (Windows mutex)"
                )
                return False

            self._mutex_handle = handle
            self._write_pid_info()
            _log.info(
                "Singelinstanslås taget: Windows mutex (%s)",
                mutex_name,
            )
            return True

        except Exception as exc:
            _log.debug("Windows mutex ej tillgänglig: %s", exc)
            return None

    def _acquire_flock(self) -> Optional[bool]:
        """
        POSIX flock på låsfil. OS släpper låset vid processdöd.

        Returns:
            True/False vid avgjort resultat,
            None om metoden inte kunde användas (-> nästa metod).
        """

        try:
            import fcntl

            self._lock_dir.mkdir(parents=True, exist_ok=True)
            # Hålls öppen så länge processen lever
            lock_file = open(
                self._lock_path, "a+", encoding="utf-8"
            )

            try:
                fcntl.flock(
                    lock_file.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except (BlockingIOError, OSError):
                lock_file.close()
                _log.info("Annan instans kör redan (flock)")
                return False

            # Skriv vår PID i låsfilen (informativt)
            try:
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.write(
                    f"{os.getpid()}\n"
                    f"{datetime.now().isoformat(timespec='seconds')}\n"
                )
                lock_file.flush()
                os.fsync(lock_file.fileno())
            except Exception:
                pass

            self._flock_file = lock_file
            self._write_pid_info()
            _log.info(
                "Singelinstanslås taget: flock (%s)",
                self._lock_path,
            )
            return True

        except Exception as exc:
            _log.debug("flock ej tillgänglig: %s", exc)
            return None

    def _acquire_pidfile(self) -> bool:
        """
        PID-fil-fallback med stale-detektering.
        Används endast om mutex/flock saknas.
        """

        try:
            if self._pid_path.exists():
                try:
                    content = self._pid_path.read_text(
                        encoding="utf-8"
                    ).strip()
                    existing_pid = int(content.splitlines()[0])
                except (ValueError, IndexError):
                    existing_pid = -1

                if existing_pid > 0 and _pid_is_running(
                    existing_pid
                ):
                    _log.info(
                        "Annan instans kör redan "
                        "(PID-fil, pid=%d)",
                        existing_pid,
                    )
                    return False

                _log.warning(
                    "Stale PID-fil hittad (pid=%s död) — "
                    "tar över låset",
                    existing_pid,
                )

            self._write_pid_info()
            _log.info(
                "Singelinstanslås taget: PID-fil (%s)",
                self._pid_path,
            )
            return True

        except Exception as exc:
            _log.error(
                "PID-fil-lås misslyckades: %s", exc, exc_info=True,
            )
            # Hellre tillåta start än att blockera felaktigt
            return True

    def _write_pid_info(self) -> None:
        """Skriv PID-fil (atomiskt). Informativ + fallback-lås."""

        try:
            _atomic_write_text(
                self._pid_path,
                f"{os.getpid()}\n"
                f"{datetime.now().isoformat(timespec='seconds')}\n",
            )
        except Exception as exc:
            _log.debug("Kunde inte skriva PID-fil: %s", exc)

    # ──────────────────────────────────────────────────────────────────
    # CLEANUP-REGISTRERING (atexit + signaler)

    # ──────────────────────────────────────────────────────────────────

    def _post_acquire(self) -> None:
        """Markera taget lås + registrera cleanup-hooks."""

        self._acquired = True
        self._register_cleanup()

    def _register_cleanup(self) -> None:
        """
        Registrera cleanup vid exit + signaler. Körs en gång.
        Kedjar vidare till tidigare signalhanterare.
        """

        if self._cleanup_registered:
            return
        self._cleanup_registered = True

        atexit.register(self.release)

        signals = [signal.SIGINT, signal.SIGTERM]
        if IS_WINDOWS and hasattr(signal, "SIGBREAK"):
            signals.append(signal.SIGBREAK)

        for sig in signals:
            try:
                prev = signal.getsignal(sig)
                self._prev_handlers[sig] = prev
                signal.signal(sig, self._signal_handler)
            except (ValueError, OSError, RuntimeError) as exc:
                # ValueError: ej main thread — ofarligt,
                # atexit täcker normal exit
                _log.debug(
                    "Kunde inte registrera signal %s: %s",
                    sig, exc,
                )

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Släpp låset vid signal och kedja vidare."""

        _log.info(
            "Signal %s mottagen — släpper singelinstanslås",
            signum,
        )
        try:
            self.release()
        except Exception:
            pass

        prev = self._prev_handlers.get(signum)
        if callable(prev):
            try:
                prev(signum, frame)
                return
            except Exception:
                pass
        # Default: avsluta med konventionell signalexitkod
        sys.exit(128 + int(signum))

    # ──────────────────────────────────────────────────────────────────
    # HJÄLPARE

    # ──────────────────────────────────────────────────────────────────

    @staticmethod

    def _sanitize_name(name: str) -> str:
        """Sanera låsnamn till säkra tecken (fil-/mutexnamn)."""

        cleaned = "".join(
            c if c.isalnum() or c in ("_", "-") else "_"
            for c in str(name).strip()
        )
        return cleaned or DEFAULT_LOCK_NAME

    # ──────────────────────────────────────────────────────────────────
    # CONTEXT MANAGER

    # ──────────────────────────────────────────────────────────────────

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb) -> bool:
        self.release()
        return False

    def __repr__(self) -> str:
        return (
            f"<SingleInstance v{VERSION} "
            f"name={self._lock_name} "
            f"acquired={self._acquired} "
            f"method={self._method}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
# EXPORTS

# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "SingleInstance",
    "DEFAULT_LOCK_NAME",
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
