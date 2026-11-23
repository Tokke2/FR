"""Låst Swish-QR, PayPal/Ko-fi som knappar, licens och borttagna betallänkar."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import donation  # noqa: E402


class DonationDataTests(unittest.TestCase):
    def test_payment_data_is_fast_and_not_configurable(self):
        source = (ROOT / 'core' / 'donation.py').read_text(encoding='utf-8')
        self.assertNotIn('0721817177', source)
        self.assertNotIn('config', source.casefold())
        self.assertNotIn('os.environ', source)
        self.assertNotIn('open(', source)
        self.assertEqual(donation.PAYPAL_URL, 'https://paypal.me/Rickard3dPrint')
        self.assertEqual(donation.KOFI_URL, 'https://ko-fi.com/tokke2')
        # Endast Swish har QR-kod. PayPal och Ko-fi ska aldrig få en egen kod.
        self.assertEqual(set(donation.QR_CODES), {'swish'})
        self.assertFalse(hasattr(donation, 'PAYPAL_URL_QR'))
        self.assertFalse(hasattr(donation, 'KOFI_URL_QR'))
        config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        text = json.dumps(config).casefold()
        for word in ('swish', 'paypal', 'ko-fi', 'kofi', 'donation', 'stod'):
            self.assertNotIn(word, text)

    def test_qr_matrix_is_well_formed(self):
        matrix = donation.swish_qr_matrix()
        self.assertEqual(len(matrix), 29)
        self.assertTrue(all(len(row) == 29 for row in matrix))
        # Fasta sökmönster i tre hörn och vit tyst zon runt koden.
        for y, x in ((4, 4), (4, 18), (18, 4)):
            self.assertEqual(matrix[y][x:x + 7], '1111111')
            self.assertEqual(matrix[y + 6][x:x + 7], '1111111')
        self.assertTrue(all(set(row[:4] + row[-4:]) == {'0'} for row in matrix))
        self.assertEqual(matrix[0], '0' * 29)

    def test_qr_decodes_to_personal_swish_number(self):
        try:
            import numpy as np
            import zxingcpp
        except ImportError:  # pragma: no cover - endast utan testberoenden
            self.skipTest('QR-avkodning kräver zxing-cpp i testmiljön')
        matrix = donation.swish_qr_matrix()
        modules = np.array([[0 if c == '0' else 255 for c in row] for row in matrix], dtype=np.uint8)
        # Den färdiga koden ska avläsas som en vanlig Swish-QR för det privata numret.
        result = zxingcpp.read_barcode(np.kron(modules, np.ones((8, 8), dtype=np.uint8)))
        self.assertIsNotNone(result)
        self.assertEqual(result.text, 'A0721817177')

    def test_damaged_qr_is_rejected(self):
        label, original = donation.QR_CODES['swish']
        broken = list(original)
        broken[10] = broken[10][:-1]
        donation.QR_CODES['swish'] = (label, tuple(broken))
        try:
            with self.assertRaises(ValueError):
                donation.swish_qr_matrix()
        finally:
            donation.QR_CODES['swish'] = (label, original)


class SwishDialogTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'swish_qr_dialog.py').read_text(encoding='utf-8')
        self.license_source = (ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'license_dialog.py').read_text(encoding='utf-8')

    def test_no_link_or_editable_surface(self):
        for forbidden in ('QLineEdit', 'QSpinBox', 'QComboBox', 'QTextEdit', 'QWebEngine',
                          'urllib', 'requests', 'http.client', 'socket'):
            self.assertNotIn(forbidden, self.source)
        # Adresserna får bara komma från den låsta datamodulen, aldrig skrivas här.
        self.assertNotIn('paypal.me', self.source)
        self.assertNotIn('ko-fi.com', self.source)
        self.assertIn('QPlainTextEdit', self.license_source)
        self.assertIn('setReadOnly(True)', self.license_source)

    def test_paypal_and_kofi_are_fixed_and_whitelisted(self):
        self.assertEqual(donation.PAYPAL_URL, 'https://paypal.me/Rickard3dPrint')
        self.assertEqual(donation.KOFI_URL, 'https://ko-fi.com/tokke2')
        self.assertIn('ALLOWED_URLS = frozenset({PAYPAL_URL, KOFI_URL})', self.source)
        self.assertIn('if url not in ALLOWED_URLS:', self.source)
        self.assertFalse((ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'support_dialog.py').exists())
        config = (ROOT / 'config.json').read_text(encoding='utf-8').casefold()
        for word in ('paypal', 'ko-fi', 'kofi', 'swish'):
            self.assertNotIn(word, config)

    def test_dialog_has_a_real_donation_text(self):
        for text in (donation.INTRO_TEXT, donation.BODY_TEXT, donation.NEVER_TEXT, donation.QR_HINT):
            self.assertGreater(len(text.split()), 12)
        self.assertIn('frivillig', donation.BODY_TEXT.casefold())
        self.assertIn('låses upp', donation.NEVER_TEXT.casefold())
        self.assertIn('Rickard Längkvist', donation.FOOTER_TEXT)
        self.assertIn('Skanna', donation.QR_HINT)
        self.assertIn('Swish', donation.BODY_TEXT)
        self.assertIn('QR_HINT', self.source)
        self.assertIn('NEVER_TEXT', self.source)
        self.assertIn('INTRO_TITLE', self.source)
        self.assertIn('LINK_HINT', self.source)
        self.assertIn('PayPal', donation.LINK_HINT)
        self.assertIn('Ko-fi', donation.LINK_HINT)

    def test_only_the_swish_qr_code_is_rendered(self):
        self.assertIn('render_qr_pixmap', self.source)
        self.assertIn("self._qr_label('swish'", self.source)
        # PayPal och Ko-fi får bara finnas som knappar – aldrig som QR-kod.
        self.assertEqual(self.source.count('self._qr_label('), 1)  # bara Swish-kortet
        for forbidden in ('PAYPAL_URL_QR', 'KOFI_URL_QR', "self._qr_label('paypal'",
                          "self._qr_label('kofi'", "self._qr_label(name"):
            self.assertNotIn(forbidden, self.source)
        matrix = donation.qr_matrix('swish')
        self.assertEqual(len(matrix), len(matrix[0]))
        self.assertGreaterEqual(len(matrix), 21)
        self.assertEqual(matrix[0], '0' * len(matrix))
        for name in ('paypal', 'kofi'):
            with self.assertRaises(ValueError):
                donation.qr_matrix(name)

    def test_paypal_and_kofi_have_buttons_but_no_qr(self):
        for object_name in ("'paypal'", "'kofi'"):
            self.assertIn(object_name, self.source)
        self.assertIn('Öppna {label}', self.source)
        self.assertIn('knappar, ingen QR-kod', self.source)
        # Ingen QR-panel i knappkortet.
        card = self.source.split('def _link_card', 1)[1].split('def _free_note', 1)[0]
        self.assertNotIn('_qr_label', card)
        self.assertNotIn('render_qr_pixmap', card)

    def test_swish_qr_decodes_and_other_names_are_rejected(self):
        try:
            import numpy as np
            import zxingcpp
        except ImportError:  # pragma: no cover
            self.skipTest('QR-avkodning kräver zxing-cpp i testmiljön')
        matrix = donation.qr_matrix('swish')
        modules = np.array([[0 if c == '0' else 255 for c in row] for row in matrix], dtype=np.uint8)
        result = zxingcpp.read_barcode(np.kron(modules, np.ones((8, 8), dtype=np.uint8)))
        self.assertIsNotNone(result)
        self.assertEqual(result.text, 'A0721817177')
        with self.assertRaises(ValueError):
            donation.qr_matrix('okand')

    def test_menu_actions_exist(self):
        menu = (ROOT / 'plugins' / 'main_gui' / 'plugin.py').read_text(encoding='utf-8')
        self.assertIn('Stöd Fordonsreg (donation)', menu)
        self.assertIn('_show_swish_qr', menu)
        self.assertNotIn('_show_support', menu)
        self.assertIn('Licens och användningsvillkor', menu)
        self.assertIn('_show_license', menu)

    def test_support_lives_in_the_app_only(self):
        # Stödet finns enbart i programmet – ingen egen webbsida i repot.
        for name in ('stod.html', 'stöd.html', 'support.html', 'donation.html'):
            self.assertFalse((ROOT / name).exists(), name)
        self.assertFalse((ROOT / 'docs' / 'stod.html').exists())
        html = [p for p in ROOT.rglob('*.html') if '.git' not in p.parts and 'node_modules' not in p.parts]
        for page in html:
            text = page.read_text(encoding='utf-8', errors='ignore').casefold()
            self.assertNotIn('ko-fi.com/tokke2', text, page)
            self.assertNotIn('paypal.me/rickard3dprint', text, page)


class LicenseTests(unittest.TestCase):
    def test_license_grants_private_and_commercial_use(self):
        text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('Rickard Längkvist', text)
        self.assertIn('privata och kommersiella', text)
        self.assertIn('ändra', text)
        self.assertIn('tredjepartsmaterial', text.casefold())
        self.assertLessEqual((ROOT / 'LICENSE').stat().st_size, 65536)
        self.assertFalse((ROOT / 'LICENSE').is_symlink())

    def test_license_dialog_reads_bundled_file(self):
        path = ROOT / 'plugins' / 'main_gui' / 'dialogs' / 'license_dialog.py'
        namespace = {'__file__': str(path)}
        code = path.read_text(encoding='utf-8')
        self.assertIn("parents[3] / 'LICENSE'", code)
        self.assertIn('is_symlink()', code)
        compiled = compile(code, str(path), 'exec')
        self.assertIsNotNone(compiled)


if __name__ == '__main__':
    unittest.main()
