"""Starta Fordonsreg med beroendekontroll före GUI-start."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
# Ingen terminal ska synas, inte ens om appen startats med python.exe.
try:
    from core.no_console import gui_executable, hidden_kwargs, hide_console_window
except Exception:  # pragma: no cover - startfilen får aldrig krascha här
    gui_executable = lambda: sys.executable  # noqa: E731
    hidden_kwargs = lambda: {}  # noqa: E731
    hide_console_window = lambda: False  # noqa: E731
hide_console_window()
from core.error_summary import ErrorSummaryHandler
try:
    from core.dependencies import pip_command, probe, outdated_packages
except Exception:
    # Även fel före själva beroendekontrollen ska synas i felloggen.
    try:
        early_log = logging.getLogger("filregistrering.start")
        early_log.addHandler(ErrorSummaryHandler(ROOT / "logs", "startkontroll"))
        try:
            from core.daily_logging import DailyLogHandler
            early_log.addHandler(DailyLogHandler(ROOT / "logs", "startkontroll"))
        except Exception:
            pass
        early_log.exception("Startkontrollens kod kunde inte läsas in")
    except Exception:
        pass
    raise


def _message(title: str, text: str, question: bool = False) -> bool:
    """Visa dialog även om PySide6 inte är installerat."""
    if sys.platform == "win32":
        try:
            import ctypes
            flags = 0x24 if question else 0x30
            result = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
            return result == 6 if question else True
        except Exception:
            pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        try:
            # Tk används innan Qt är tillgängligt. Behåll bildobjektet vid liv.
            try:
                icon = tk.PhotoImage(file=str(ROOT / "ikon_64.png"))
                window.iconphoto(True, icon)
            except Exception:
                pass
            if question:
                return bool(messagebox.askyesno(title, text, parent=window))
            messagebox.showinfo(title, text, parent=window)
            return True
        finally:
            window.destroy()
    except Exception:
        pass
    # Linux kan ha zenity utan tkinter. macOS har osascript som fallback.
    if sys.platform.startswith("linux"):
        import shutil
        if shutil.which("zenity"):
            args = ["zenity", "--question" if question else "--info", "--title", title, "--text", text]
            return subprocess.run(args, check=False, **hidden_kwargs()).returncode == 0
    if sys.platform == "darwin":
        # Skicka text som argument, inte som AppleScript-kod.
        script = ('on run argv\nset r to display dialog (item 2 of argv) with title (item 1 of argv) '
                  + ('buttons {"Nej", "Ja"} default button "Ja"' if question else 'buttons {"OK"} default button "OK"')
                  + '\nend run')
        try:
            return subprocess.run(["osascript", "-e", script, title, text], check=False,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  **hidden_kwargs()).returncode == 0
        except OSError:
            pass
    if sys.stdin is not None and sys.stdin.isatty():
        print(f"{title}: {text}")
        if question:
            return input("Installera? [j/N] ").strip().lower() in {"j", "ja", "y", "yes"}
        return True
    return False


def setup_log():
    logs = ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("filregistrering.start")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        handler = RotatingFileHandler(logs / "bootstrap.log", maxBytes=5*1024*1024,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(handler)
    if not any(isinstance(h, ErrorSummaryHandler) for h in log.handlers):
        log.addHandler(ErrorSummaryHandler(logs, "startkontroll"))
    try:
        from core.daily_logging import DailyLogHandler
        if not any(isinstance(h, DailyLogHandler) for h in log.handlers):
            log.addHandler(DailyLogHandler(logs, "startkontroll", monitor=True))
    except Exception as exc:
        log.warning("Kunde inte starta dagsloggningen: %s", exc)
    return log


def _run_pip(log, packages, *, upgrade=False) -> bool:
    """Ändra bara godkända paket i den Python som redan kör appen."""
    try:
        result = subprocess.run(pip_command(packages, upgrade=upgrade), cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=600,
                                **hidden_kwargs())
        if result.returncode:
            raise RuntimeError(f"pip returnerade status {result.returncode}")
        log.info("pip slutförde %s för %s", "uppgradering" if upgrade else "installation", packages)
        return True
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        # Skriv inte pips output: den kan innehålla privata paketkällor.
        log.error("pip misslyckades: %s", exc)
        _message("Python-tillägg", "Paket kunde inte installeras eller uppdateras i den aktuella Pythonmiljön. Kontrollera pip, internet och behörigheter. Se logs/bootstrap.log.")
        return False


def check_dependencies(log, *, deferred: list | None = None) -> bool:
    """Kontrollera de fyra apptilläggen, och fråga innan miljön ändras."""
    try:
        result = probe()
        missing, broken = result["missing"], result["broken"]
        log.info("Beroendekontroll: saknas=%s, trasiga=%s", missing, list(broken))
        skip_updates = ()
        if missing:
            text = ("Följande Python-tillägg saknas: " + ", ".join(missing)
                    + "\n\nInstallera dem i den aktuella Pythonmiljön? Andra program som använder samma miljö kan påverkas."
                    + (" Installationen sker när appen avslutas." if deferred is not None else ""))
            if not _message("Installera Python-tillägg", text, question=True):
                log.warning("Installation av saknade tillägg avböjdes")
                return False
            if deferred is not None:
                existing = {name for _, queued in deferred for name in queued}
                remaining = [name for name in missing if name not in existing]
                if remaining:
                    deferred.append((False, remaining))
                skip_updates = tuple(missing)
                missing = []
            else:
                if not _run_pip(log, missing):
                    return False
                result = probe()
                missing, broken = result["missing"], result["broken"]
        if missing or broken:
            log.error("Beroenden kan inte användas: saknas=%s, trasiga=%s", missing, broken)
            details = "\n".join(f"{name}: {error}" for name, error in broken.items())
            _message("Pythonmiljön behöver åtgärdas", "Alla tillägg kan inte användas. Kontrollera Pythonversion och systembibliotek.\n\n" + details)
            return False
        try:
            updates = outdated_packages(skip=skip_updates)
        except Exception as exc:
            log.warning("Kunde inte kontrollera tilläggsuppdateringar: %s", exc)
            _message("Python-tillägg", "Kunde inte kontrollera om tilläggen har uppdateringar. Inga tillägg uppdaterades. Se logs/bootstrap.log.")
            return True
        if not updates:
            log.info("Inga tilläggsuppdateringar hittades")
            return True
        names = [item['name'] for item in updates]
        lines = "\n".join(f"{item['name']}: {item['version']} → {item['latest_version']}" for item in updates)
        text = ("Uppdateringar finns för Fordonsregs Python-tillägg:\n\n" + lines
                + "\n\nUppdatera i den befintliga Pythonmiljön? pip kan även ändra paketens beroenden och andra program kan påverkas."
                + (" Ändringarna görs först när du avslutat appen." if deferred is not None else ""))
        if not _message("Uppdatera Python-tillägg?", text, question=True):
            log.info("Användaren avböjde uppdatering av Python-tillägg")
            return True
        if deferred is not None:
            existing = {name for _, queued in deferred for name in queued}
            remaining = [name for name in names if name not in existing]
            if remaining:
                deferred.append((True, remaining))
            return True
        # Även ett misslyckat pip kan ha ändrat delar. Kontrollera därför alltid
        # att de viktigaste paketen går att importera innan appstarten fortsätter.
        _run_pip(log, names, upgrade=True)
        result = probe()
        if result['missing'] or result['broken']:
            log.error("Python-tillägg fungerar inte efter uppdateringen: %s", result)
            _message("Python-tillägg", "Tilläggen kunde inte verifieras efter uppdateringen. Se logs/bootstrap.log.")
            return False
        return True
    except Exception as exc:
        log.exception("Beroendekontrollen misslyckades")
        _message("Python-tillägg", f"Tilläggen kunde inte kontrolleras: {exc}. Se logs/bootstrap.log.")
        return False


def _claim_weekly(log) -> bool | None:
    try:
        from core.weekly_maintenance import claim_due
        return claim_due(ROOT / "logs")
    except Exception as exc:
        log.warning("Veckokontrollens status kunde inte läsas eller sparas: %s", exc)
        _message("Pythonkontroll", "Veckokontrollens status kunde inte läsas eller sparas. Ingen automatisk kontroll eller uppdatering körs. Se logs/bootstrap.log.")
        return None


def _weekly_monitor(log, stop, package_queue):
    """Kör kontrollen medan GUI:t är öppet; ändringar väntar tills det stängts."""
    while not stop.wait(30):
        due = _claim_weekly(log)
        if due is None:
            return  # Undvik upprepade fel och dialoger om statusfilen inte kan användas.
        if due:
            log.info("Veckokontroll startar medan appen är öppen")
            check_dependencies(log, deferred=package_queue)


def _apply_deferred(log, packages) -> None:
    """Utför godkänt underhåll först efter att GUI-processen avslutats."""
    for upgrade, names in packages:
        if not _run_pip(log, names, upgrade=upgrade):
            log.warning("Återstående planerade ändringar avbröts efter pip-fel")
            return
    if packages:
        try:
            result = probe()
            if result['missing'] or result['broken']:
                raise RuntimeError("Tilläggen kunde inte verifieras efter uppdateringen")
        except Exception as exc:
            log.error("Tilläggens efterkontroll misslyckades: %s", exc)
            _message("Python-tillägg", "Tilläggen kunde inte verifieras efter uppdateringen. Se logs/bootstrap.log.")
            return
    if packages:
        _message("Python-tillägg", "Tilläggen uppdaterades i den befintliga Pythonmiljön. Starta appen igen när du vill använda dem.")


def _startup_health(log, root) -> None:
    """Återställ en uppdatering som aldrig bekräftades innan appen startar."""
    try:
        from core.startup_health import check_and_recover
        result = check_and_recover(root)
        if result.get("recovered"):
            log.warning("Föregående start bekräftades inte; %d fil(er) återställdes från säkerhetskopian",
                        len(result["recovered"]))
        elif result.get("error"):
            log.error("Starthälsokontrollen: %s", result["error"])
    except Exception:
        log.exception("Starthälsokontrollen kunde inte genomföras")


def main() -> int:
    try:
        log = setup_log()
    except OSError as exc:
        _message("Fordonsreg", f"Kan inte skapa loggkatalogen: {exc}")
        return 1
    log.info("Appstart: Python %s", sys.version.split()[0])
    from core.single_instance import SingleInstance, LAUNCHER_LOCK_NAME
    launcher = SingleInstance(LAUNCHER_LOCK_NAME)
    if not launcher.acquire():
        if launcher.error:
            _message("Fordonsreg", "Starten avbröts: " + launcher.error)
            return 1
        if not SingleInstance().focus_existing():
            _message("Fordonsreg", "Den befintliga starten kunde inte kontaktas. Se logs/bootstrap.log.")
            return 1
        return 0
    try:
        # Hantera också en app som redan startats direkt utan startkontrollen.
        app_lock = SingleInstance()
        if not app_lock.acquire():
            if app_lock.error:
                _message("Fordonsreg", "Starten avbröts: " + app_lock.error)
                return 1
            if not app_lock.focus_existing():
                _message("Fordonsreg", "Den befintliga appen kunde inte kontaktas. Se logs/bootstrap.log.")
                return 1
            return 0
        app_lock.release()
        return _run_with_launcher_lock(log)
    finally:
        launcher.release()


def _run_with_launcher_lock(log) -> int:
    try:
        due = _claim_weekly(log)
        if due:
            log.info("Veckokontroll för tillägg påbörjas; befintlig Python ändras inte")
            if not check_dependencies(log):
                return 1
        elif due is False:
            log.info("Tillägg har redan kontrollerats eller försökt kontrolleras denna vecka")
        _startup_health(log, ROOT)
        log.info("Startar appen")
        env = dict(os.environ)
        env["FR_PREFLIGHT_DONE"] = "1"
        # Bevara tidiga startfel, Qt-meddelanden och utskrift från processen.
        output_log = logging.getLogger("filregistrering.process_output")
        output_log.setLevel(logging.DEBUG)
        handler = RotatingFileHandler(ROOT / "logs/console.log", maxBytes=10*1024*1024,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        output_log.addHandler(handler)
        daily_output = None
        try:
            from core.daily_logging import DailyLogHandler
            daily_output = DailyLogHandler(ROOT / "logs", "processutskrift")
            output_log.addHandler(daily_output)
        except Exception as exc:
            log.warning("Kunde inte starta dagsloggning av processutskrift: %s", exc)
        try:
            # pythonw.exe startar appen utan konsol; flaggorna döljer processen
            # även om bara python.exe finns tillgängligt.
            child = subprocess.Popen([gui_executable(), str(ROOT / "main.pyw"), *sys.argv[1:]],
                                     cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, **hidden_kwargs())
            stop_monitor = threading.Event()
            package_queue = []
            monitor = None
            if due is not None:
                monitor = threading.Thread(target=_weekly_monitor, args=(log, stop_monitor, package_queue),
                                           name="python-weekly-maintenance", daemon=True)
                monitor.start()
            try:
                assert child.stdout is not None
                while chunk := child.stdout.read1(4096):
                    output_log.info("%s", chunk.decode("utf-8", errors="replace").rstrip())
                code = child.wait()
            finally:
                stop_monitor.set()
                if monitor is not None:
                    monitor.join()
        finally:
            output_log.removeHandler(handler)
            handler.close()
            if daily_output is not None:
                output_log.removeHandler(daily_output)
                daily_output.close()
        if code:
            log.error("Approcessen avslutades med status %s; se logs/console.log för processens utskrift", code)
        else:
            log.info("Approcessen avslutades med status %s", code)
            _apply_deferred(log, package_queue)
        if code and package_queue:
            log.warning("Planerat tilläggsunderhåll avbröts eftersom appen inte avslutades normalt")
            _message("Pythonkontroll", "Det planerade underhållet utfördes inte eftersom appen inte avslutades normalt.")
        return code
    except Exception:
        log.exception("Starten misslyckades")
        _message("Fordonsreg", "Starten misslyckades. Se logs/bootstrap.log.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
