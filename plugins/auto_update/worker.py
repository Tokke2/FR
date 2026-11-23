"""Fristående hjälpprocess: installerar först när appens pipe stängs vid exit."""
from __future__ import annotations
import logging
from pathlib import Path
import sys
import time

def main() -> int:
    root, archive_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "auto_update.log", level=logging.INFO, encoding="utf-8")
    log = logging.getLogger(__name__)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from core.error_summary import ErrorSummaryHandler
        logging.getLogger().addHandler(ErrorSummaryHandler(log_dir, "uppdatering"))
        try:
            from core.daily_logging import DailyLogHandler
            logging.getLogger().addHandler(DailyLogHandler(log_dir, "uppdatering"))
        except Exception as exc:
            log.warning("Kunde inte starta dagsloggning: %s", exc)
        from updater import install, release_files
        # Endast föräldern håller pipens skrivände; EOF betyder att appen avslutats.
        sys.stdin.buffer.read()
        # Vänta tills även startprocessen och eventuellt godkänt underhåll
        # avslutats. Ta låsen i samma ordning som startprocessen; en ny start
        # kan aldrig läsa filer samtidigt som de byts ut.
        from core.single_instance import SingleInstance, LAUNCHER_LOCK_NAME
        launcher = SingleInstance(LAUNCHER_LOCK_NAME)
        deadline = time.monotonic() + 120
        while not launcher.acquire():
            if launcher.error or time.monotonic() >= deadline:
                log.warning("Uppdateringen skjuts upp: startprocessen kör eller låset saknas")
                return 1
            time.sleep(0.25)
        try:
            lock = SingleInstance()
            if not lock.acquire():
                log.warning("Uppdateringen skjuts upp: appen kör redan eller låset saknas")
                return 1
            try:
                files = release_files(archive_path.read_bytes())
                count, backup = install(root, files)
                log.info("Installerade %d filer. Säkerhetskopia: %s", count, backup)
                # Markören tas bort först när appen startat och fungerar.
                # Annars återställs säkerhetskopian vid nästa start.
                try:
                    from core.startup_health import mark_pending
                    mark_pending(root, backup, list(files))
                except Exception as exc:
                    log.warning("Starthälsokontrollen kunde inte förberedas: %s", exc)
                return 0
            finally:
                lock.release()
        finally:
            launcher.release()
    except Exception:
        log.exception("Automatisk uppdatering misslyckades")
        return 1
    finally:
        archive_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
