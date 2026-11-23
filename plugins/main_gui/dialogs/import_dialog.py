"""Gemensam, försiktig filimport för Fordonsdata och Återförsäljare."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
import subprocess
import sys
import tempfile

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QInputDialog,
                               QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout)
from PySide6.QtCore import Qt

from core.no_console import hidden_kwargs
from core.tabular_import import (DELIMITERS, PDF_DELIMITERS, ImportFormatError, PdfDependencyMissing,
                                 excel_sheets, read_csv, read_excel, read_pdf,
                                 to_temporary_xlsx)

_log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]


def _choose(parent, title, text, options):
    value, accepted = QInputDialog.getItem(parent, title, text, list(options), 0, False)
    return value if accepted else None


def _install_pdf_reader(parent) -> bool:
    answer = QMessageBox.question(
        parent, 'PDF-läsning',
        'PDF-import kräver Python-tillägget pypdf. Installera det i den Pythonmiljö '
        'som Fordonsreg redan använder? pip kan påverka andra program i samma miljö. '
        'Ingen separat Pythoninstallation skapas.',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    from plugins.main_gui.dialogs.task_progress import run_task
    def install(progress):
        progress(0, 0, 'Installerar pypdf i befintlig Pythonmiljö...')
        try:
            # Inget terminalfönster får visas när tillägget installeras.
            result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-input', 'pypdf'],
                                    capture_output=True, timeout=180, **hidden_kwargs())
            if result.returncode:
                raise RuntimeError(f'pip misslyckades med status {result.returncode}. Ingen systemspärr kringgås.')
            probe = subprocess.run([sys.executable, '-c', 'from pypdf import PdfReader'],
                                   capture_output=True, timeout=30, **hidden_kwargs())
            if probe.returncode:
                raise RuntimeError('pypdf kunde inte verifieras efter installationen')
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError('pypdf kunde inte installeras eller verifieras') from exc
    try:
        run_task(parent, 'Installerar PDF-stöd', install)
        importlib.invalidate_caches()
        return True
    except Exception as exc:
        _log.warning('PDF-stödet kunde inte installeras: %s', exc)
        QMessageBox.warning(parent, 'PDF-läsning', f'{exc}\n\nKontrollera den befintliga Pythonmiljön och försök igen.')
        return False


def _read_in_background(parent, label: str, reader):
    """Läs tunga filer utanför GUI-tråden. Avbryts läsningen ändras ingenting.

    Kan bakgrundskörningen inte startas läses filen i GUI-tråden i stället;
    importen fungerar då som tidigare, bara utan förloppsruta.
    """
    try:
        from plugins.main_gui.background import run_cancellable
    except Exception as exc:  # Qt-trådar saknas eller kan inte importeras
        _log.warning('Bakgrundsläsning är inte tillgänglig (%s); läser i GUI-tråden', exc)
        return reader()

    def work(progress):
        progress(0, 0, label)
        return reader()

    try:
        outcome = run_cancellable(parent, label, work)
    except Exception as exc:
        _log.warning('Bakgrundsläsningen kunde inte startas (%s); läser i GUI-tråden', exc)
        return reader()
    if outcome.get('cancelled'):
        _log.info('Filläsningen avbröts av användaren')
        return None
    if outcome.get('error') is not None:
        raise outcome['error']
    return outcome.get('value')


def _table_from_file(parent, path: Path):
    suffix = path.suffix.lower()
    if suffix in ('.xlsx', '.xls', '.xlsm'):
        sheets = excel_sheets(path)
        if not sheets:
            raise ImportFormatError('Arbetsboken saknar blad')
        sheet = _choose(parent, 'Välj blad', 'Vilket Excelblad innehåller tabellen?', sheets)
        if sheet is None:
            return None
        table = _read_in_background(parent, 'Läser Excelbladet...', lambda: read_excel(path, sheet))
        return table
    if suffix in ('.csv', '.pdf'):
        delimiters = PDF_DELIMITERS if suffix == '.pdf' else DELIMITERS
        choice = _choose(parent, 'Kolumnseparator',
                         'Välj hur tabellens kolumner skiljs åt. PDF måste vara en textbaserad tabell.',
                         delimiters)
        if choice is None:
            return None
        delimiter = delimiters[choice]
        label = 'Läser PDF-tabellen...' if suffix == '.pdf' else 'Läser CSV-filen...'
        if suffix == '.csv':
            return _read_in_background(parent, label, lambda: read_csv(path, delimiter))
        try:
            return _read_in_background(parent, label, lambda: read_pdf(path, delimiter))
        except PdfDependencyMissing:
            if not _install_pdf_reader(parent):
                return None
            return _read_in_background(parent, label, lambda: read_pdf(path, delimiter))
    raise ImportFormatError('Välj en Excel-, CSV- eller PDF-fil')


def _preview_pdf(parent, table) -> bool:
    # Visa varje rad – en PDF:s läsordning kan annars ge felaktiga värden.
    if len(table.rows) > 200 or len(table.headers) > 50:
        raise ImportFormatError('PDF-tabellen är för stor för säker fullständig granskning (max 200 rader och 50 kolumner).')
    dialog = QDialog(parent)
    dialog.setWindowTitle('Granska hela tabellen från PDF')
    dialog.resize(900, 550)
    layout = QVBoxLayout(dialog)
    label = QLabel('Kontrollera alla värden och kolumner mot PDF-originalet. Importen avbryts om du inte godkänner.')
    label.setWordWrap(True); layout.addWidget(label)
    view = QTableWidget(len(table.rows), len(table.headers), dialog)
    view.setHorizontalHeaderLabels(list(table.headers))
    for r, values in enumerate(table.rows):
        for c, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            view.setItem(r, c, item)
    layout.addWidget(view)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _import_dealers(parent, app, dealer_page, table):
    from core.dealer_import import CONTEXT, FIELDS, plan
    from core.learning import LearningStore
    from core.vehicle_mapping_profiles import ProfileStore
    from plugins.main_gui.vehicle_registry_helpers import ColumnMappingDialog, _normalize_header

    plugin = app.get_plugin('dealers_manager')
    if plugin is None or getattr(plugin, '_json_path', None) is None:
        raise ImportFormatError('Återförsäljarregistret är inte tillgängligt')
    store = plugin._storage()
    existing, snapshot = store.snapshot()
    headers = list(table.headers)
    normalized = [_normalize_header(h) for h in headers]
    learning = LearningStore(ROOT / 'json/mappings/learning.json')
    try:
        initial = learning.suggestions(CONTEXT, normalized, FIELDS)
    except Exception as exc:
        _log.warning('Kunde inte läsa inlärda dealermappningar: %s', exc)
        initial = {}
    examples = {key: [f'{table.sheet}: {row[i]}' for row in table.rows[:3] if row[i]]
                for i, key in enumerate(normalized)}
    dialog = ColumnMappingDialog(headers=headers, initial_mapping=initial, target_labels=FIELDS,
                                 parent=parent, examples=examples, learned_headers=list(initial),
                                 allow_pin=False,
                                 profile_store=ProfileStore(ROOT / 'json/mappings/dealer_import_profiles.json'))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    mapping = dialog.get_mapping()
    draft = plan(table, mapping, existing)
    choices = {}
    for conflict in draft['conflicts']:
        old, new = conflict['existing'], conflict['incoming']
        changes = [f"{FIELDS[key]}: {old.get(key, '')} → {value}"
                   for key, value in new.items() if key != 'dealer_number'
                   and str(old.get(key, '')).strip() != value]
        choice = _choose(parent, 'Dealernummer finns redan',
                         f"{conflict['dn']}\n" + "\n".join(changes) + "\n\nVad ska göras?",
                         ['Avbryt importen', 'Behåll befintlig', 'Uppdatera befintlig'])
        if choice is None or choice == 'Avbryt importen':
            return
        choices[conflict['dn']] = 'skip' if choice == 'Behåll befintlig' else 'replace'
    draft = plan(table, mapping, existing, choices)
    answer = QMessageBox.question(
        parent, 'Bekräfta import',
        f"Nya: {draft['added']}\nUppdateras: {draft['changed']}\nOförändrade: {draft['unchanged']}\n"
        f"Överhoppade: {draft['skipped']}\n\nFortsätta? En säkerhetskopia görs före ändring.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    if draft['added'] or draft['changed']:
        from plugins.main_gui.dialogs.dealer_pin import request_pin
        pin = request_pin(parent, plugin)
        if pin is None:
            return
        if not plugin.save_to_json(draft['rows'], expected=snapshot, pin=pin):
            raise ImportFormatError('Återförsäljarregistret kunde inte sparas. Kontrollera PIN, ändringar och säkerhetskopiering.')
        plugin._emit_safe('dealers.imported', {'count': draft['added'] + draft['changed']})
    if dialog.save_mapping_checked() and not draft['skipped']:
        try:
            learning.observe_mapping(CONTEXT, mapping, FIELDS)
        except Exception as exc:
            _log.warning('Kunde inte spara inlärd dealermappning: %s', exc)
    if dealer_page is not None:
        dealer_page.refresh()
    QMessageBox.information(parent, 'Import klar',
                            f"{draft['added']} nya och {draft['changed']} uppdaterade återförsäljare. "
                            f"{draft['unchanged']} oförändrade, {draft['skipped']} överhoppade.")


def start_import(parent, app, vehicle_page, dealer_page, *, destination=None) -> None:
    """Välj mål och källfil. Inga ändringar sker innan respektive kontroll."""
    if destination is None:
        destination = _choose(parent, 'Importera fil', 'Var ska uppgifterna importeras?', ['Fordonsdata', 'Återförsäljare'])
    if destination is None:
        return
    if destination not in ('Fordonsdata', 'Återförsäljare'):
        raise ValueError('Ogiltigt importmål')
    filename, _ = QFileDialog.getOpenFileName(parent, 'Välj fil', '',
        'Importfiler (*.xlsx *.xls *.xlsm *.csv *.pdf);;Excel (*.xlsx *.xls *.xlsm);;CSV (*.csv);;PDF (*.pdf)')
    if not filename:
        return
    path = Path(filename)
    try:
        if destination == 'Fordonsdata' and path.suffix.lower() in ('.xlsx', '.xls', '.xlsm'):
            if vehicle_page is None:
                raise ImportFormatError('Fordonsdata är inte tillgängligt')
            vehicle_page._import_from_excel(str(path))
            return
        table = _table_from_file(parent, path)
        if table is None:
            return
        if path.suffix.lower() == '.pdf' and not _preview_pdf(parent, table):
            return
        if destination == 'Återförsäljare':
            _import_dealers(parent, app, dealer_page, table)
        else:
            if vehicle_page is None:
                raise ImportFormatError('Fordonsdata är inte tillgängligt')
            with tempfile.TemporaryDirectory(prefix='fordonsreg-import-') as temp:
                temporary = Path(temp) / 'import.xlsx'
                to_temporary_xlsx(table, temporary)
                vehicle_page._import_from_excel(str(temporary))
    except Exception as exc:
        _log.exception('Importfilen kunde inte behandlas')
        QMessageBox.warning(parent, 'Import kunde inte slutföras', str(exc))
