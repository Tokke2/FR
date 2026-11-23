from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.tabular_import import (Table, ImportFormatError, read_csv, read_excel, read_pdf, PDF_SPACING,
                                 to_temporary_xlsx, excel_sheets)
from core.dealer_import import plan
from core.dealer_storage import DealerStorage
from core.learning import LearningStore

ROOT = Path(__file__).resolve().parents[1]


class FormatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_csv_utf8_quotes_leading_zero_original_unchanged(self):
        path = self.root / 'data.csv'
        content = '\ufeffID;Namn;Extra\n0012;"Bolag; AB";=2+2\n'.encode('utf-8')
        path.write_bytes(content)
        table = read_csv(path, ';')
        self.assertEqual(table.headers, ('ID', 'Namn', 'Extra'))
        self.assertEqual(table.rows, (('0012', 'Bolag; AB', '=2+2'),))
        self.assertEqual(path.read_bytes(), content)

    def test_ambiguous_or_truncated_csv_aborts(self):
        path = self.root / 'file.csv'
        for content in ('ID;id;Namn\n1;2;A\n', 'ID;Namn\n1;A\n2\n', 'ID;Namn\n1;"open\n', 'ID,Namn\n1,A\n'):
            path.write_text(content, encoding='utf-8')
            with self.assertRaises(ImportFormatError): read_csv(path, ';')
        path.write_bytes(b'ID;Namn\n1;\xe5')
        with self.assertRaisesRegex(ImportFormatError, 'UTF-8'): read_csv(path, ';')

    def test_excel_sheet_and_numeric_padded_id_are_checked(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest('openpyxl saknas')
        path = self.root / 'dealers.xlsx'
        wb = Workbook(); sheet = wb.active; sheet.title = 'Handlare'
        sheet.append(['Dealer Number', 'Namn']); sheet.append(['0001', 'NA'])
        wb.save(path); wb.close(); original = path.read_bytes()
        self.assertEqual(excel_sheets(path), ['Handlare'])
        table = read_excel(path, 'Handlare')
        self.assertEqual(table.rows, (('0001', 'NA'),))
        self.assertEqual(path.read_bytes(), original)
        wb = Workbook(); s = wb.active; s.title = 'Handlare'
        s.append(['Dealer Number', 'Namn']); s.append([12, 'Företag']); s['A2'].number_format = '0000'
        wb.save(path); wb.close()
        with self.assertRaisesRegex(ImportFormatError, 'inledande nollor'): read_excel(path, 'Handlare')

    def test_pdf_real_text_table_and_scanned_or_multipage_rejected(self):
        try:
            from reportlab.pdfgen import canvas
            import pypdf  # noqa
        except ImportError:
            self.skipTest('PDF-testberoenden saknas')
        path = self.root / 'table.pdf'
        pdf = canvas.Canvas(str(path))
        pdf.drawString(40, 800, 'ID;Namn'); pdf.drawString(40, 780, '0001;Dealer AB'); pdf.save()
        original = path.read_bytes()
        self.assertEqual(read_pdf(path, ';').rows, (('0001', 'Dealer AB'),))
        self.assertEqual(path.read_bytes(), original)
        pdf = canvas.Canvas(str(path))
        pdf.drawString(40, 800, 'ID'); pdf.drawString(200, 800, 'Namn')
        pdf.drawString(40, 780, '0001'); pdf.drawString(200, 780, 'Dealer AB'); pdf.save()
        self.assertEqual(read_pdf(path, PDF_SPACING).rows, (('0001', 'Dealer AB'),))
        pdf = canvas.Canvas(str(path)); pdf.showPage(); pdf.save()
        with self.assertRaisesRegex(ImportFormatError, 'markerbar text'): read_pdf(path, ';')
        pdf = canvas.Canvas(str(path)); pdf.drawString(40, 800, 'ID;Namn'); pdf.drawString(40, 780, '0001;Dealer'); pdf.showPage(); pdf.drawString(40, 800, '0002;Other'); pdf.save()
        self.assertEqual(len(read_pdf(path, ';').rows), 2)
        pdf = canvas.Canvas(str(path)); pdf.drawString(40, 800, 'ID;Namn'); pdf.drawString(40, 780, '0001;Dealer'); pdf.showPage(); pdf.drawString(40, 800, 'ID;Namn'); pdf.drawString(40, 780, '0002;Other'); pdf.save()
        with self.assertRaisesRegex(ImportFormatError, 'upprepade rubriker'): read_pdf(path, ';')
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(path); writer = PdfWriter(); writer.add_page(reader.pages[0]); writer.encrypt('secret')
        locked = self.root / 'locked.pdf'
        with locked.open('wb') as stream: writer.write(stream)
        with self.assertRaisesRegex(ImportFormatError, 'Lösenordsskyddad'): read_pdf(locked, ';')

    def test_vehicle_import_rejects_colliding_headers_and_duplicate_targets(self):
        try:
            import pandas as pd
        except ImportError:
            self.skipTest('pandas saknas')
        from plugins.vehicle_registry.plugin import VehicleDataStorage
        from plugins.vehicle_registry.excel_importer import ExcelModelImporter
        storage = VehicleDataStorage(self.root / 'vehicles')
        importer = ExcelModelImporter(vehicle_storage=storage, mapping_dir=self.root / 'mappings')
        duplicate = self.root / 'duplicate.xlsx'
        pd.DataFrame([['ABC', 'ABC', '2024']], columns=['VIN CODE', 'VIN_CODE', 'YEAR']).to_excel(duplicate, index=False)
        result = importer.import_file(str(duplicate), column_mapping={'VINCODE': 'vin_kod', 'YEAR': '_year'}, save_mapping=False)
        self.assertFalse(result['success'])
        self.assertIn('tvetydiga', result['errors'][0])
        no_collision = self.root / 'duplicate_target.xlsx'
        pd.DataFrame({'VINCODE': ['ABC'], 'YEAR': ['2024'], 'TYPE': ['A'], 'OTHER': ['B']}).to_excel(no_collision, index=False)
        result = importer.import_file(str(no_collision), column_mapping={'VINCODE': 'vin_kod', 'YEAR': '_year', 'TYPE': 'typ', 'OTHER': 'typ'}, save_mapping=False)
        self.assertFalse(result['success'])
        self.assertIn('samma målfält', result['errors'][0])
        self.assertFalse((self.root / 'vehicles' / '2024.json').exists())

    def test_temporary_excel_keeps_formula_like_cells_as_text(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest('openpyxl saknas')
        table = Table(('VINCODE', 'YEAR', 'MODELNAME'), (('ABC', '2024', '=1+1'), ('DEF', '2024', 'NA'), ('GHI', '2024', 'None')))
        path = self.root / 'tmp.xlsx'; to_temporary_xlsx(table, path)
        wb = load_workbook(path, data_only=False)
        self.assertEqual(wb.active['C2'].value, '=1+1')
        self.assertEqual(wb.active['C2'].data_type, 's')
        wb.close()
        from plugins.vehicle_registry.plugin import VehicleDataStorage
        from plugins.vehicle_registry.excel_importer import ExcelModelImporter
        storage = VehicleDataStorage(self.root / 'vehicles')
        importer = ExcelModelImporter(vehicle_storage=storage, mapping_dir=self.root / 'mappings')
        result = importer.import_file(str(path), column_mapping={'VINCODE': 'vin_kod', 'YEAR': '_year', 'MODELNAME': 'modellkod'}, save_mapping=False)
        self.assertTrue(result['success'], result)
        self.assertEqual(storage.load_year(2024)[0]['modellkod'], '=1+1')
        self.assertEqual(storage.load_year(2024)[1]['modellkod'], 'NA')
        self.assertEqual(storage.load_year(2024)[2]['modellkod'], 'None')


class DealerPlanTests(unittest.TestCase):
    def setUp(self):
        self.table = Table(('Dealer Number', 'Namn', 'Org nr'), (('001', 'New Name', '123'), ('002', 'Second', '456')))
        self.mapping = {'DEALERNUMBER': 'dealer_number', 'NAMN': 'namn', 'ORGNR': 'orgnr'}
        self.existing = [{'dealer_number': '001', 'namn': 'Old', 'orgnr': '123', 'extra': 'keep'}]

    def test_conflict_is_explicit_and_replace_preserves_extra(self):
        draft = plan(self.table, self.mapping, self.existing)
        self.assertEqual(len(draft['conflicts']), 1)
        self.assertEqual(self.existing[0]['namn'], 'Old')
        resolved = plan(self.table, self.mapping, self.existing, {'001': 'replace'})
        self.assertEqual(resolved['changed'], 1); self.assertEqual(resolved['added'], 1)
        self.assertEqual(resolved['rows'][0]['extra'], 'keep')
        self.assertEqual(resolved['rows'][0]['namn'], 'New Name')
        skipped = plan(self.table, self.mapping, self.existing, {'001': 'skip'})
        self.assertEqual(skipped['rows'][0], self.existing[0]); self.assertEqual(skipped['skipped'], 1)

    def test_duplicate_input_or_existing_and_missing_required_abort(self):
        for table in (Table(self.table.headers, (('1', 'A', ''), ('1', 'B', ''))),
                      Table(self.table.headers, (('', 'A', ''),))):
            with self.assertRaises(ImportFormatError): plan(table, self.mapping, self.existing)
        with self.assertRaises(ImportFormatError): plan(self.table, self.mapping, self.existing * 2)
        with self.assertRaises(ImportFormatError): plan(self.table, {'DEALERNUMBER': 'dealer_number'}, self.existing)
        with self.assertRaises(ImportFormatError): plan(self.table, {**self.mapping, 'EXTRA': 'namn'}, self.existing)

    def test_extended_contact_fields_have_explicit_conflicts_and_are_preserved(self):
        table = Table(('ID', 'Name', 'Address', 'Town'), (('001', 'New Name', 'New road', 'Kista'),))
        mapping = {'ID': 'dealer_number', 'NAME': 'namn', 'ADDRESS': 'adress', 'TOWN': 'ort'}
        existing = [{'dealer_number': '001', 'namn': 'New Name', 'adress': 'Old road', 'land': 'SE'}]
        draft = plan(table, mapping, existing)
        self.assertEqual(len(draft['conflicts']), 1)
        self.assertEqual(draft['conflicts'][0]['incoming']['adress'], 'New road')
        result = plan(table, mapping, existing, {'001': 'replace'})
        self.assertEqual(result['rows'][0]['ort'], 'Kista')
        self.assertEqual(result['rows'][0]['land'], 'SE')

    def test_omitted_orgnr_is_not_cleared(self):
        table = Table(('DN', 'Name'), (('001', 'Updated'),))
        result = plan(table, {'DN': 'dealer_number', 'NAME': 'namn'}, self.existing, {'001': 'replace'})
        self.assertEqual(result['rows'][0]['orgnr'], '123')


class DialogIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = types.ModuleType('PySide6'); package.__path__ = []
        widgets = types.ModuleType('PySide6.QtWidgets')
        for name in ('QDialog', 'QDialogButtonBox', 'QFileDialog', 'QInputDialog', 'QLabel', 'QMessageBox', 'QTableWidget', 'QTableWidgetItem', 'QVBoxLayout'):
            setattr(widgets, name, type(name, (), {}))
        widgets.QDialog.DialogCode = SimpleNamespace(Accepted=1)
        widgets.QMessageBox.StandardButton = SimpleNamespace(Yes=1, No=2)
        widgets.QMessageBox.question = Mock(return_value=1)
        widgets.QMessageBox.warning = Mock(); widgets.QMessageBox.information = Mock()
        core = types.ModuleType('PySide6.QtCore'); core.Qt = SimpleNamespace()
        self.mods = {'PySide6': package, 'PySide6.QtWidgets': widgets, 'PySide6.QtCore': core}
        loader = importlib.machinery.SourceFileLoader('test_import_dialog_module', str(ROOT / 'plugins/main_gui/dialogs/import_dialog.py'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.mod = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, self.mods): loader.exec_module(self.mod)
        self.mod.ROOT = self.root
        self.widgets = widgets

    def test_dealer_dialog_import_uses_safe_backup_and_learns(self):
        from plugins.vehicle_registry.excel_importer import _normalize_column_name
        path = self.root / '.js data/aterforsaljare.json'; storage = DealerStorage(path)
        existing = [{'dealer_number': '001', 'namn': 'Old', 'orgnr': '123', 'unknown': 7}]
        storage.save(existing, None)
        plugin = SimpleNamespace(_json_path=path, _storage=lambda: storage, _emit_safe=Mock(),
                                 save_to_json=lambda rows, expected, pin: (storage.save(rows, expected), True)[1])
        app = SimpleNamespace(get_plugin=lambda name: plugin)
        class Dialog:
            def __init__(self, **kwargs): pass
            def exec(self): return 1
            def get_mapping(self): return {'ID': 'dealer_number', 'NAME': 'namn', 'ORG': 'orgnr'}
            def save_mapping_checked(self): return True
        helpers = types.ModuleType('plugins.main_gui.vehicle_registry_helpers')
        helpers.ColumnMappingDialog = Dialog; helpers._normalize_header = _normalize_column_name
        table = Table(('ID', 'Name', 'Org'), (('001', 'New', '123'), ('002', 'Another', '456')), 'sheet')
        page = SimpleNamespace(refresh=Mock())
        with patch.dict(sys.modules, {**self.mods, 'plugins.main_gui.vehicle_registry_helpers': helpers,
                                      'plugins.main_gui.dialogs.dealer_pin': SimpleNamespace(request_pin=lambda *args: '123456')}), \
             patch.object(self.mod, '_choose', return_value='Uppdatera befintlig'):
            self.mod._import_dealers(object(), app, page, table)
        data, _ = storage.snapshot()
        self.assertEqual(data[0]['namn'], 'New'); self.assertEqual(data[0]['unknown'], 7)
        self.assertEqual(data[1]['dealer_number'], '002')
        self.assertEqual(len(list(storage.backup_dir.iterdir())), 2)
        memory = LearningStore(self.root / 'json/mappings/learning.json')
        self.assertEqual(memory.status()['rules'], 3)
        self.assertEqual(memory.suggestions('dealer_import.v1', ['ID'], ['dealer_number']), {})
        with patch.dict(sys.modules, {**self.mods, 'plugins.main_gui.vehicle_registry_helpers': helpers}):
            self.mod._import_dealers(object(), app, page, table)
        self.assertEqual(memory.suggestions('dealer_import.v1', ['ID'], ['dealer_number']), {'ID': 'dealer_number'})
        self.assertEqual(memory.suggestions('vehicle_import.v1', ['ID'], ['dealer_number']), {})
        self.assertEqual(page.refresh.call_count, 2)

    def test_import_canceled_at_pin_never_saves_or_learns(self):
        from plugins.vehicle_registry.excel_importer import _normalize_column_name
        path = self.root / '.js data/aterforsaljare.json'; storage = DealerStorage(path)
        storage.save([{'dealer_number': '001', 'namn': 'Old'}], None)
        before = path.read_bytes()
        plugin = SimpleNamespace(_json_path=path, _storage=lambda: storage,
                                 _emit_safe=Mock(), save_to_json=Mock())
        class Dialog:
            def __init__(self, **kwargs): pass
            def exec(self): return 1
            def get_mapping(self): return {'ID': 'dealer_number', 'NAME': 'namn'}
            def save_mapping_checked(self): return True
        helpers = types.ModuleType('plugins.main_gui.vehicle_registry_helpers')
        helpers.ColumnMappingDialog = Dialog; helpers._normalize_header = _normalize_column_name
        pin = SimpleNamespace(request_pin=Mock(return_value=None))
        table = Table(('ID', 'Name'), (('001', 'New'),), 'sheet')
        with patch.dict(sys.modules, {**self.mods, 'plugins.main_gui.vehicle_registry_helpers': helpers,
                                      'plugins.main_gui.dialogs.dealer_pin': pin}), \
             patch.object(self.mod, '_choose', return_value='Uppdatera befintlig'):
            self.mod._import_dealers(object(), SimpleNamespace(get_plugin=lambda name: plugin), None, table)
        pin.request_pin.assert_called_once()
        plugin.save_to_json.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'json/mappings/learning.json').exists())

    def test_shared_dialog_passes_csv_to_existing_vehicle_import_and_cleans_temp(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest('openpyxl saknas')
        source = self.root / 'vehicle.csv'
        source.write_text('VINCODE;YEAR;MODEL\nABC;2024;Motorbike\n')
        original = source.read_bytes(); seen = []
        def import_vehicle(filename):
            workbook = load_workbook(filename)
            seen.append((Path(filename), workbook.active['A2'].value))
            workbook.close()
        page = SimpleNamespace(_import_from_excel=import_vehicle)
        self.widgets.QFileDialog.getOpenFileName = Mock(return_value=(str(source), ''))
        with patch.dict(sys.modules, self.mods), patch.object(self.mod, '_choose', side_effect=['Fordonsdata', 'Semikolon (;)']):
            self.mod.start_import(object(), object(), page, None)
        self.assertEqual(seen[0][1], 'ABC')
        self.assertFalse(seen[0][0].exists())
        self.assertEqual(source.read_bytes(), original)
        self.widgets.QMessageBox.warning.assert_not_called()

    def test_pdf_preview_rejection_prevents_import(self):
        source = self.root / 'test.pdf'; source.write_bytes(b'test')
        table = Table(('ID', 'Name'), (('1', 'A'),), 'pdf')
        self.widgets.QFileDialog.getOpenFileName = Mock(return_value=(str(source), ''))
        with patch.dict(sys.modules, self.mods), patch.object(self.mod, '_choose', return_value='Återförsäljare'),              patch.object(self.mod, '_table_from_file', return_value=table), patch.object(self.mod, '_preview_pdf', return_value=False),              patch.object(self.mod, '_import_dealers') as importer:
            self.mod.start_import(object(), object(), None, None)
        importer.assert_not_called()

    def test_pdf_dependency_installation_requires_explicit_consent(self):
        self.widgets.QMessageBox.question.return_value = 2
        with patch('subprocess.run') as run:
            self.assertFalse(self.mod._install_pdf_reader(object()))
            run.assert_not_called()
        self.widgets.QMessageBox.question.return_value = 1
        task = types.ModuleType('plugins.main_gui.dialogs.task_progress')
        task.run_task = lambda parent, title, work: work(lambda *args: None)
        result = SimpleNamespace(returncode=0)
        with patch.dict(sys.modules, {'plugins.main_gui.dialogs.task_progress': task}), patch('subprocess.run', return_value=result) as run:
            self.assertTrue(self.mod._install_pdf_reader(object()))
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, '-m', 'pip', 'install', '--no-input', 'pypdf'])
        self.assertEqual(run.call_args_list[1].args[0], [sys.executable, '-c', 'from pypdf import PdfReader'])

    def test_dealer_cancel_or_concurrent_change_never_writes(self):
        from plugins.vehicle_registry.excel_importer import _normalize_column_name
        path = self.root / '.js data/aterforsaljare.json'; storage = DealerStorage(path)
        existing = [{'dealer_number': '001', 'namn': 'Old'}]; storage.save(existing, None)
        plugin = SimpleNamespace(_json_path=path, _storage=lambda: storage, _emit_safe=Mock(),
                                 save_to_json=lambda rows, expected, pin: (storage.save(rows, expected), True)[1])
        app = SimpleNamespace(get_plugin=lambda name: plugin)
        class Dialog:
            def __init__(self, **kwargs): pass
            def exec(self): return 1
            def get_mapping(self): return {'ID': 'dealer_number', 'NAME': 'namn'}
            def save_mapping_checked(self): return True
        helpers = types.ModuleType('plugins.main_gui.vehicle_registry_helpers')
        helpers.ColumnMappingDialog = Dialog; helpers._normalize_header = _normalize_column_name
        table = Table(('ID', 'Name'), (('001', 'New'),), 'sheet')
        before = path.read_bytes()
        with patch.dict(sys.modules, {**self.mods, 'plugins.main_gui.vehicle_registry_helpers': helpers}), patch.object(self.mod, '_choose', return_value='Avbryt importen'):
            self.mod._import_dealers(object(), app, None, table)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'json/mappings/learning.json').exists())
        def changed(*args):
            path.write_text(json.dumps([{'dealer_number': '001', 'namn': 'External'}]))
            return 'Uppdatera befintlig'
        with patch.dict(sys.modules, {**self.mods, 'plugins.main_gui.vehicle_registry_helpers': helpers, 'plugins.main_gui.dialogs.dealer_pin': SimpleNamespace(request_pin=lambda *args: '123456')}), patch.object(self.mod, '_choose', side_effect=changed):
            with self.assertRaises(ValueError): self.mod._import_dealers(object(), app, None, table)
        self.assertEqual(storage.snapshot()[0][0]['namn'], 'External')
        self.assertFalse((self.root / 'json/mappings/learning.json').exists())


if __name__ == '__main__':
    unittest.main()
