"""Årsindelning för Fordonsdata, utan att flytta användarens datafiler."""
from __future__ import annotations

FIRST_YEAR = 2021
ACTIVE_YEARS_AFTER_MODEL_YEAR = 5


def is_archived_year(year: int, current_year: int) -> bool:
    """Årsfliken 2021 arkiveras vid årsskiftet till 2027, inte under 2026."""
    return year < current_year - ACTIVE_YEARS_AFTER_MODEL_YEAR


def initial_years(current_year: int, stored_years=(), requested_years=()) -> list[int]:
    """Visa varje år från 2021 samt alla redan sparade eller begärda år."""
    return sorted(set(range(FIRST_YEAR, current_year + 1)) | set(stored_years) | set(requested_years))
