from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from plugins.auto_update import updater

ROOT = Path(__file__).resolve().parents[1]


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, value in entries.items():
            z.writestr('release/' + name, value)
    return out.getvalue()


class VectorBrandingTests(unittest.TestCase):
    def test_print_logo_is_text_free_vector_with_transparent_background(self):
        path = ROOT / 'assets/fordonsreg-logo.svg'
        raw = path.read_bytes()
        updater._validate_brand_svg(path.as_posix(), raw)
        root = ET.fromstring(raw)
        ns = '{http://www.w3.org/2000/svg}'
        self.assertEqual(root.get('width'), '112mm')
        self.assertEqual(root.get('height'), '112mm')
        self.assertTrue(root.get('viewBox'))
        tags = [node.tag for node in root.iter()]
        self.assertGreaterEqual(tags.count(ns + 'path'), 2)
        self.assertNotIn(ns + 'image', tags)
        self.assertNotIn(ns + 'text', tags)
        self.assertNotIn(ns + 'rect', tags)
        self.assertNotIn(b'data:', raw)

    def test_svg_release_allowlist_and_backup(self):
        name = 'assets/fordonsreg-logo.svg'
        data = (ROOT / name).read_bytes()
        files = updater.release_files(archive({name: data, 'assets/private.svg': b'<svg/>', 'data/data.json': b'{}'}))
        self.assertEqual(files, {name: data})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'assets').mkdir()
            (root / name).write_bytes(b'old user version')
            count, backup = updater.install(root, files)
            self.assertEqual(count, 1)
            self.assertEqual((backup / name).read_bytes(), b'old user version')
            self.assertEqual((root / name).read_bytes(), data)
        for bad in (b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>',
                    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><script/></svg>',
                    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><image href="https://example.org/a"/></svg>',
                    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path fill="url(https://example.org/x)" d="M0 0Z"/></svg>'):
            with self.assertRaises(updater.UpdateError): updater.release_files(archive({name: bad}))

    def test_release_archive_delivers_print_artwork_with_the_program(self):
        names = ('assets/fordonsreg-logo.svg', 'assets/fordonsreg-icon.svg',
                 'assets/LOGOTYP.md', 'ikon.ico', 'ikon_16.png', 'ikon_32.png',
                 'ikon_64.png', 'ikon_256.png')
        contents = {name: (ROOT / name).read_bytes() for name in names}
        contents.update({'main.pyw': b'pass\n', 'assets/private.svg': b'not allowed'})
        files = updater.release_files(archive(contents))
        self.assertEqual(set(files), set(names) | {'main.pyw'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            count, backup = updater.install(root, files)
            self.assertEqual(count, len(files))
            self.assertIsNotNone(backup)
            for name in names:
                self.assertEqual((root / name).read_bytes(), contents[name])
            self.assertEqual(updater.changed_files(root, files), {})
        for bad in (b'bad\x00text', b'\xff', b'a' * 65537):
            with self.assertRaises(updater.UpdateError):
                updater.release_files(archive({'assets/LOGOTYP.md': bad}))

    def test_icon_pixels_are_nonempty_and_match_vector(self):
        try:
            from PIL import Image, ImageChops
            import resvg_py
        except ImportError:
            self.skipTest('Bildtestberoenden saknas')
        svg = (ROOT / 'assets/fordonsreg-icon.svg').read_text()
        rendered = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, width=256, height=256))).convert('RGBA')
        with Image.open(ROOT / 'ikon_256.png') as source:
            actual = source.convert('RGBA')
        self.assertEqual(actual.size, (256, 256))
        self.assertIsNotNone(actual.getbbox())
        # Appikonen är antialiasad från en större rasterisering av samma vektor.
        diff = ImageChops.difference(actual, rendered)
        self.assertLess(sum(diff.convert('RGB').resize((1, 1)).getpixel((0, 0))), 12)
        with Image.open(ROOT / 'ikon.ico') as ico:
            self.assertTrue({(16,16), (32,32), (64,64), (256,256)}.issubset(ico.info['sizes']))


if __name__ == '__main__':
    unittest.main()
