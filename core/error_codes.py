"""Felkoder med förklaring och åtgärdssteg (förslag 24).

Guiden beskriver vad koden betyder, trolig orsak och vad användaren kan göra.
Den ändrar aldrig en felposts status: en kod markeras som åtgärdad först när
programmet självt verifierat det (i dag endast CONFIG_PARSE_ERROR).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

MAX_GUIDE_TEXT = 600

GUIDES: dict[str, dict] = {
    "CONFIG_PARSE_ERROR": {
        "title": "Konfigurationsfilen kunde inte läsas som JSON",
        "cause": ("Ett kommatecken, citattecken eller en parentes saknas i config.json, "
                  "eller så har filen sparats i ett annat format."),
        "steps": [
            "Öppna config.json i en textredigerare och kontrollera raden som anges i loggen.",
            "Jämför med senaste säkerhetskopia i .update-backups om felet uppstod efter en ändring.",
            "Spara filen som UTF-8 utan BOM och starta om Fordonsreg.",
        ],
        "verified": True,
    },
    "PLUGIN_LOAD_ERROR": {
        "title": "En plugin kunde inte laddas",
        "cause": "Pluginmappen saknas, plugin.py är skadad eller så krockar namnet med en annan plugin.",
        "steps": [
            "Kontrollera att mappen under plugins/ innehåller plugin.py.",
            "Läs raden ovanför felet i loggen – där anges vilken plugin det gäller.",
            "Återställ pluginens filer från senaste uppdateringsbackup om de ändrats nyligen.",
        ],
        "verified": False,
    },
    "PLUGIN_INIT_ERROR": {
        "title": "En plugin kraschade när den startades",
        "cause": "Ett beroende saknas, en inställning är ogiltig eller pluginens datafil är skadad.",
        "steps": [
            "Kontrollera veckokontrollens status i logs/python_underhall.json.",
            "Läs traceback-raden i felsökningsloggen för att se vilken fil som felar.",
            "Starta om programmet efter att beroendet installerats.",
        ],
        "verified": False,
    },
    "PLUGIN_ACTIVATION_ERROR": {
        "title": "En plugin kunde inte aktiveras",
        "cause": "Pluginens aktiveringssteg avbröts, ofta på grund av en låst eller skadad datafil.",
        "steps": [
            "Stäng andra instanser av Fordonsreg.",
            "Kontrollera att datafiler inte är öppna i Excel eller ett annat program.",
            "Starta om och läs loggen om felet kvarstår.",
        ],
        "verified": False,
    },
    "DEPENDENCY_ERROR": {
        "title": "Ett Python-tillägg saknas eller fungerar inte",
        "cause": "Ett av tilläggen (PySide6, pandas, openpyxl, xlrd) är inte installerat i den Pythonmiljö som används.",
        "steps": [
            "Godkänn tilläggsinstallationen när Fordonsreg frågar vid nästa veckokontroll.",
            "Kontrollera att startfilen använder samma Python som tilläggen installerades i.",
            "Öppna en terminal och kör: python -m pip install <tillägg> om du vill göra det själv.",
        ],
        "verified": False,
    },
    "EVENT_EMIT_ERROR": {
        "title": "En händelse kunde inte skickas",
        "cause": "En lyssnare kastade ett fel när händelsen levererades.",
        "steps": [
            "Sök i loggen efter raden strax före felet för att se vilken lyssnare som avbröt.",
            "Starta om programmet – felet påverkar normalt bara den enstaka åtgärden.",
        ],
        "verified": False,
    },
    "EVENT_SUBSCRIPTION_ERROR": {
        "title": "En lyssnare kunde inte registreras",
        "cause": "En plugin försökte registrera en lyssnare med ogiltiga argument.",
        "steps": [
            "Kontrollera att alla plugins har samma version som resten av programmet.",
            "Återställ de senast uppdaterade filerna om felet uppstod efter en uppdatering.",
        ],
        "verified": False,
    },
    "EVENT_NOT_CANCELLABLE": {
        "title": "En händelse kunde inte avbrytas",
        "cause": "Händelsen är markerad som icke avbrytbar men en lyssnare försökte avbryta den.",
        "steps": ["Läs vilken händelse som anges i loggen och rapportera den om felet upprepas."],
        "verified": False,
    },
    "INVALID_MIDDLEWARE": {
        "title": "Ogiltig mellanhand för händelser",
        "cause": "En middleware registrerades utan att vara anropbar.",
        "steps": ["Kontrollera nyligen ändrad plugin-kod eller återställ från backup."],
        "verified": False,
    },
    "CONFIG_NOT_FOUND": {
        "title": "Konfigurationsfilen hittades inte",
        "cause": "config.json fattas i programmappen eller så anger APP_CONFIG en felaktig sökväg.",
        "steps": [
            "Kontrollera att config.json finns i programmets rotmapp.",
            "Ta bort en egen APP_CONFIG-variabel om du satt en sådan av misstag.",
            "Starta Fordonsreg igen – standardvärden används om filen saknas.",
        ],
        "verified": False,
    },
}


def guide_for(code: str) -> dict | None:
    """Returnera guide för en felkod, eller None om koden är okänd."""
    if not isinstance(code, str):
        return None
    entry = GUIDES.get(code.strip().upper())
    if entry is None:
        return None
    return {
        "code": code.strip().upper(),
        "title": entry["title"][:MAX_GUIDE_TEXT],
        "cause": entry["cause"][:MAX_GUIDE_TEXT],
        "steps": [step[:MAX_GUIDE_TEXT] for step in entry["steps"]],
        "automatic_resolution": bool(entry.get("verified")),
    }


def guide_lines(code: str) -> list[str]:
    """Färdiga textrader för visning i felsökningsvyn."""
    entry = guide_for(code)
    if entry is None:
        return [f"Ingen åtgärdsguide finns för felkoden {code!r}.",
                "Läs raden i felsökningsloggen och kontakta support om felet upprepas."]
    lines = [f"{entry['code']} – {entry['title']}", "", f"Trolig orsak: {entry['cause']}", "", "Gör så här:"]
    lines.extend(f"{index}. {step}" for index, step in enumerate(entry["steps"], start=1))
    lines.append("")
    lines.append("Koden markeras automatiskt som åtgärdad när programmet verifierat det."
                 if entry["automatic_resolution"] else
                 "Koden markeras inte automatiskt som åtgärdad eftersom lösningen inte kan verifieras.")
    return lines


def read_entries(path: Path) -> list[dict]:
    """Läs felkodsregistret skrivskyddat. Skadade filer ger en tom lista."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _log.warning("Felkodsregistret kunde inte läsas: %s", exc)
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return []
    rows = []
    for key, entry in entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("code"), str):
            continue
        rows.append({
            "key": key,
            "code": entry["code"],
            "status": entry.get("status", "okänd"),
            "message": str(entry.get("message", ""))[:MAX_GUIDE_TEXT],
            "count": entry.get("count", 0),
            "last_seen": entry.get("last_seen"),
            "known": entry["code"] in GUIDES,
        })
    rows.sort(key=lambda row: str(row.get("last_seen") or ""), reverse=True)
    return rows


def summary(entries: list[dict]) -> str:
    """Kort text för instrumentpanelen."""
    active = [row for row in entries if row.get("status") == "aktiv"]
    if not active:
        return "Inga aktiva felkoder."
    known = sum(1 for row in active if row.get("known"))
    return f"{len(active)} aktiva felkoder, varav {known} har en åtgärdsguide."
