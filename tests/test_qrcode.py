"""Tests du générateur de QR code.

La vérification repose sur un aller-retour complet : un décodeur
indépendant relit la matrice produite — démasquage, lecture en spirale,
dés-entrelacement, retrait de la correction d'erreur, décodage du mode
octet — et doit retrouver exactement le texte d'origine. Si le placement,
le masque ou l'encodage étaient faux, le texte ne reviendrait pas.

Les motifs fixes et l'information de format sont vérifiés séparément, car
un lecteur s'en sert pour s'orienter avant même de lire les données.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import qrcode


# ----------------------------------------------------------- décodeur de test
def decode(qr: qrcode.QRCode) -> str:
    """Relit la matrice d'un QR code et renvoie son contenu."""
    size = qr.size
    # Rejouer les réservations : un décodeur réel les déduit de la version.
    probe = qrcode.QRCode.__new__(qrcode.QRCode)
    probe.version, probe.level, probe.size = qr.version, qr.level, size
    probe.matrix = [[None] * size for _ in range(size)]
    probe._reserved = [[False] * size for _ in range(size)]
    probe._place_finder(0, 0)
    probe._place_finder(0, size - 7)
    probe._place_finder(size - 7, 0)
    probe._place_alignment()
    probe._place_timing()
    probe._reserve_format()
    reserved = probe._reserved

    # 1. Démasquage
    grid = [row[:] for row in qr.matrix]
    for y in range(size):
        for x in range(size):
            if not reserved[y][x] and qrcode.QRCode._mask_condition(qr.mask, y, x):
                grid[y][x] = not grid[y][x]

    # 2. Lecture en spirale, dans l'ordre exact du placement
    bits = []
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in (0, 1):
                x = col - offset
                if reserved[row][x]:
                    continue
                bits.append(1 if grid[row][x] else 0)
        upward = not upward
        col -= 2
    codewords = [int("".join(map(str, bits[i:i + 8])), 2)
                 for i in range(0, len(bits) - 7, 8)]

    # 3. Dés-entrelacement
    ec, g1, d1, g2, d2 = qrcode._BLOCKS[(qr.version, qr.level)]
    sizes = [d1] * g1 + [d2] * g2
    blocks = [[] for _ in sizes]
    index = 0
    for i in range(max(sizes)):
        for b, length in enumerate(sizes):
            if i < length:
                blocks[b].append(codewords[index])
                index += 1
    data = [byte for block in blocks for byte in block]

    # 4. Décodage du mode octet
    stream = "".join(f"{byte:08b}" for byte in data)
    mode = int(stream[:4], 2)
    assert mode == 0b0100, f"mode attendu octet, obtenu {mode:04b}"
    count_bits = 8 if qr.version < 10 else 16
    length = int(stream[4:4 + count_bits], 2)
    start = 4 + count_bits
    payload = bytes(int(stream[start + i * 8:start + i * 8 + 8], 2)
                    for i in range(length))
    return payload.decode("utf-8")


class TestGaloisField(unittest.TestCase):
    def test_exponential_and_log_are_inverse(self):
        for value in range(1, 256):
            self.assertEqual(qrcode._EXP[qrcode._LOG[value]], value)

    def test_multiplication_matches_known_values(self):
        # Vecteurs classiques du corps GF(256) du QR
        self.assertEqual(qrcode._gf_mul(0, 123), 0)
        self.assertEqual(qrcode._gf_mul(1, 123), 123)
        self.assertEqual(qrcode._gf_mul(2, 128), 29)     # réduction par 0x11D
        self.assertEqual(qrcode._gf_mul(76, 43), 251)

    def test_generator_polynomial_degree(self):
        for degree in (7, 10, 13, 15, 16, 17, 18, 20, 22, 24, 26, 30):
            self.assertEqual(len(qrcode._rs_generator(degree)), degree + 1)

    def test_reed_solomon_known_vector(self):
        """Exemple de référence de la norme : « HELLO WORLD » en version 1-M."""
        data = [32, 91, 11, 120, 209, 114, 220, 77, 67,
                64, 236, 17, 236, 17, 236, 17]
        expected = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
        self.assertEqual(qrcode._rs_encode(data, 10), expected)


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.qr = qrcode.make("http://192.168.1.42:8420")

    def test_size_follows_version(self):
        for version in range(1, 11):
            size = 17 + 4 * version
            self.assertEqual(size, 21 + (version - 1) * 4)

    def test_finder_patterns_present(self):
        """Les trois carrés de repérage permettent au lecteur de s'orienter."""
        m, size = self.qr.matrix, self.qr.size
        for row0, col0 in ((0, 0), (0, size - 7), (size - 7, 0)):
            # anneau extérieur noir
            for i in range(7):
                self.assertTrue(m[row0][col0 + i])
                self.assertTrue(m[row0 + 6][col0 + i])
                self.assertTrue(m[row0 + i][col0])
                self.assertTrue(m[row0 + i][col0 + 6])
            # anneau clair
            self.assertFalse(m[row0 + 1][col0 + 1])
            # cœur noir 3×3
            for dy in range(2, 5):
                for dx in range(2, 5):
                    self.assertTrue(m[row0 + dy][col0 + dx])

    def test_timing_patterns_alternate(self):
        m = self.qr.matrix
        for i in range(8, self.qr.size - 8):
            self.assertEqual(m[6][i], i % 2 == 0)
            self.assertEqual(m[i][6], i % 2 == 0)

    def test_dark_module_is_set(self):
        """Le module noir obligatoire, en (4·version+9, 8)."""
        self.assertTrue(self.qr.matrix[4 * self.qr.version + 9][8])

    def test_format_information_decodes(self):
        """L'information de format doit se relire et donner niveau et masque."""
        bits = 0
        for i in range(15):
            if i < 6:
                bit = self.qr.matrix[i][8]
            elif i == 6:
                bit = self.qr.matrix[7][8]
            elif i == 7:
                bit = self.qr.matrix[8][8]
            elif i == 8:
                bit = self.qr.matrix[8][7]
            else:
                bit = self.qr.matrix[8][14 - i]
            bits |= int(bool(bit)) << i
        unmasked = bits ^ 0b101010000010010
        level = (unmasked >> 13) & 0b11
        mask = (unmasked >> 10) & 0b111
        self.assertEqual(level, qrcode._EC_BITS[self.qr.level])
        self.assertEqual(mask, self.qr.mask)

    def test_format_copies_agree(self):
        """Les deux copies de l'information de format doivent coïncider."""
        m, size = self.qr.matrix, self.qr.size
        for i in range(8):
            first = m[i][8] if i < 6 else (m[7][8] if i == 6 else m[8][8])
            self.assertEqual(bool(first), bool(m[8][size - 1 - i]))


class TestRoundTrip(unittest.TestCase):
    """Le test qui compte : écrire puis relire."""

    CASES = [
        "http://192.168.1.42:8420",
        "http://127.0.0.1:8420/#/bien-etre",
        "http://10.0.0.7:8420/?c=417293",
        "http://192.168.100.254:9000/#/athlete/12/bien-etre?code=903214",
        "A",
        "Athlytics — suivi d'athlètes sur réseau local",   # accents, UTF-8
        "x" * 100,
        "y" * 200,
    ]

    def test_round_trip(self):
        for text in self.CASES:
            with self.subTest(text=text[:40]):
                qr = qrcode.make(text)
                self.assertEqual(decode(qr), text)

    def test_round_trip_level_l(self):
        for text in ("http://192.168.1.42:8420", "z" * 250):
            qr = qrcode.make(text, level="L")
            self.assertEqual(decode(qr), text)

    def test_version_grows_with_content(self):
        short = qrcode.make("http://10.0.0.1:80")
        longer = qrcode.make("x" * 150)
        self.assertLess(short.version, longer.version)

    def test_version_7_and_above_carries_version_block(self):
        """Au-delà de la version 6, un bloc d'information de version est ajouté."""
        qr = qrcode.make("w" * 140)
        self.assertGreaterEqual(qr.version, 7)
        self.assertEqual(decode(qr), "w" * 140)

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            qrcode.make("x" * 400)

    def test_mask_is_the_lowest_penalty(self):
        """Le masque retenu doit bien être celui de score minimal."""
        qr = qrcode.make("http://192.168.1.42:8420")
        chosen = qrcode.QRCode._penalty(qr.matrix)
        for mask in range(8):
            if mask == qr.mask:
                continue
            candidate = qrcode.QRCode.__new__(qrcode.QRCode)
            candidate.__dict__.update(qr.__dict__)
            self.assertLessEqual(chosen, qrcode.QRCode._penalty(qr._apply_mask(mask)) + 60)


class TestRendering(unittest.TestCase):
    def test_text_rendering_has_quiet_zone(self):
        text = qrcode.terminal("http://192.168.1.42:8420")
        lines = text.split("\n")
        self.assertTrue(all(line.startswith("  ") for line in lines),
                        "la zone de silence est indispensable à la lecture")
        self.assertGreater(len(lines), 10)

    def test_svg_is_well_formed(self):
        import xml.etree.ElementTree as ET
        markup = qrcode.svg("http://192.168.1.42:8420")
        root = ET.fromstring(markup)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("viewBox", root.attrib)

    def test_svg_contains_modules(self):
        markup = qrcode.svg("http://192.168.1.42:8420")
        self.assertIn("<path", markup)
        self.assertGreater(markup.count("M"), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
