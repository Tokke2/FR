# -*- coding: utf-8 -*-

"""
plugins — Paketinit (spec v1.10)

Gör plugins/ till ett PYTHONPAKET så att relativa importer löses
korrekt i IDE/typkontroll (Pylance):

    from .plugin import Plugin          (plugins/vehicle_registry/__init__.py)
    from .excel_importer import ...     (plugins/vehicle_registry/plugin.py)
    from .vehicle_registry_helpers import ...  (main_gui/vehicle_registry_page.py)

Utan denna fil varnar IDE:n med:
    Import ".plugin" could not be resolved

PluginLoader laddar plugins via importlib.util.spec_from_file_location
med module_name "plugins.<namn>.plugin" — denna fil bryter INTE det
flödet, utan kompletterar paketstrukturen (KRAV 56, spec v1.10).

FÖRÄNDRINGAR v1.0.0 (Session 11 — spec v1.10):
  - NY FIL: paketinit för plugins/.
  - Metadata + dynamisk copyright enligt konvention.

Copyright © Rickard Längkvist (dynamiskt år, se get_copyright_string)
"""

from __future__ import annotations

import logging
from datetime import datetime

_log = logging.getLogger(__name__)

VERSION = "1.0.0"
AUTHOR = "Rickard Längkvist"


def get_copyright_string() -> str:
    """Generera copyright-sträng med dynamiskt år."""
    return "Copyright © {} {}".format(datetime.now().year, AUTHOR)


__all__ = [
    "VERSION",
    "AUTHOR",
    "get_copyright_string",
]
