"""När nästa dagliga uppdateringskontroll ska köras.

Regeln är enkel och ska vara lätt att granska: kontrollen sker **en gång per
dygn, klockan 00:00 lokal tid**. Modulen räknar bara ut tiden – den startar
ingen timer och importerar ingen Qt, så den kan testas utan gränssnitt.

Har appen varit stängd över midnatt körs kontrollen direkt vid start i stället,
eftersom ``due`` då redan har passerat.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Kontrolltiden: midnatt, lokal tid.
CHECK_HOUR = 0
CHECK_MINUTE = 0


def next_check(now: datetime | None = None) -> datetime:
    """Returnera nästa midnatt efter ``now`` (alltid i framtiden)."""
    now = now or datetime.now()
    candidate = now.replace(hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def milliseconds_until(now: datetime | None = None) -> int:
    """Antal millisekunder till nästa kontroll, för en Qt-timer.

    Qt-timers är 32-bitars och kan inte vänta ett dygn. Värdet takas därför
    och kontrollen görs om när timern har gått ut; ``is_due`` avgör då om det
    verkligen är dags.
    """
    now = now or datetime.now()
    delta = (next_check(now) - now).total_seconds()
    return max(1_000, min(int(delta * 1000), MAX_TIMER_MS))


# Qt:s intervall får vara högst 2^31-1 ms. Ett dygn är 86 400 000 ms, vilket
# ryms, men vi håller oss under gränsen med god marginal.
MAX_TIMER_MS = 1_000 * 60 * 60 * 6


def is_due(last_check: datetime | None, now: datetime | None = None) -> bool:
    """Har en kontroll inte gjorts sedan senaste midnatt?"""
    now = now or datetime.now()
    midnight = now.replace(hour=CHECK_HOUR, minute=CHECK_MINUTE, second=0, microsecond=0)
    if last_check is None:
        return True
    return last_check < midnight


def should_check_on_start(now: datetime | None = None) -> bool:
    """Kontrollen görs alltid vid start om det inte redan gjorts i dag."""
    return True
