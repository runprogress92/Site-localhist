"""Générateur de QR code, écrit sans dépendance.

Taper « http://192.168.1.42:8420 » sur un clavier de téléphone est le genre
de friction qui fait abandonner. Un QR code affiché dans le terminal et dans
l'interface supprime cette étape : on scanne, on y est.

Conforme à la norme ISO/IEC 18004, limité à ce dont l'application a besoin :

* **mode octet** (une URL contient des caractères hors alphanumérique) ;
* **versions 1 à 10** (jusqu'à 271 octets), largement suffisant ;
* **niveaux de correction L et M** : M est préféré, car un code affiché à
  l'écran subit des reflets et des angles de prise de vue.

Le découpage suit la norme : encodage → blocs → correction de Reed-Solomon
sur GF(256) → entrelacement → placement en spirale → masquage → information
de format.
"""
from __future__ import annotations

# ---------------------------------------------------------------- GF(256)
# Corps de Galois du QR : polynôme générateur x⁸+x⁴+x³+x²+1 (0x11D).
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    """Polynôme générateur de Reed-Solomon de degré donné."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            nxt[j] ^= _gf_mul(coeff, 1)
            nxt[j + 1] ^= _gf_mul(coeff, _EXP[i])
        poly = nxt
    return poly


def _rs_encode(data: list[int], ec_count: int) -> list[int]:
    """Codets de correction d'erreur pour un bloc de données."""
    generator = _rs_generator(ec_count)
    remainder = list(data) + [0] * ec_count
    for i in range(len(data)):
        factor = remainder[i]
        if factor == 0:
            continue
        for j, coeff in enumerate(generator):
            remainder[i + j] ^= _gf_mul(coeff, factor)
    return remainder[len(data):]


# ------------------------------------------------------- tables de la norme
# (version, niveau) -> (codets de correction par bloc,
#                       blocs groupe 1, données par bloc groupe 1,
#                       blocs groupe 2, données par bloc groupe 2)
_BLOCKS = {
    (1, "L"): (7, 1, 19, 0, 0),   (1, "M"): (10, 1, 16, 0, 0),
    (2, "L"): (10, 1, 34, 0, 0),  (2, "M"): (16, 1, 28, 0, 0),
    (3, "L"): (15, 1, 55, 0, 0),  (3, "M"): (26, 1, 44, 0, 0),
    (4, "L"): (20, 1, 80, 0, 0),  (4, "M"): (18, 2, 32, 0, 0),
    (5, "L"): (26, 1, 108, 0, 0), (5, "M"): (24, 2, 43, 0, 0),
    (6, "L"): (18, 2, 68, 0, 0),  (6, "M"): (16, 4, 27, 0, 0),
    (7, "L"): (20, 2, 78, 0, 0),  (7, "M"): (18, 4, 31, 0, 0),
    (8, "L"): (24, 2, 97, 0, 0),  (8, "M"): (22, 2, 38, 2, 39),
    (9, "L"): (30, 2, 116, 0, 0), (9, "M"): (22, 3, 36, 2, 37),
    (10, "L"): (18, 2, 68, 2, 69), (10, "M"): (26, 4, 43, 1, 44),
}

# Centres des motifs d'alignement, par version
_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

# Bits du niveau de correction dans l'information de format
_EC_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


def _capacity(version: int, level: str) -> int:
    """Nombre d'octets de données utiles pour une version et un niveau."""
    ec, g1, d1, g2, d2 = _BLOCKS[(version, level)]
    total = g1 * d1 + g2 * d2
    # 4 bits de mode + indicateur de longueur (8 bits jusqu'à la version 9,
    # 16 bits au-delà), soit 2 ou 3 octets de surcoût.
    overhead = 2 if version < 10 else 3
    return total - overhead


def _choose_version(length: int, level: str) -> tuple[int, str]:
    for lvl in (level, "L"):
        for version in range(1, 11):
            if (version, lvl) in _BLOCKS and _capacity(version, lvl) >= length:
                return version, lvl
    raise ValueError("Contenu trop long pour un QR code de version 10 "
                     f"({length} octets).")


# ----------------------------------------------------------------- encodage
class _BitBuffer:
    def __init__(self):
        self.bits: list[int] = []

    def put(self, value: int, width: int) -> None:
        for i in range(width - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _encode_data(text: str, version: int, level: str) -> list[int]:
    payload = text.encode("utf-8")
    ec, g1, d1, g2, d2 = _BLOCKS[(version, level)]
    total_data = g1 * d1 + g2 * d2

    buffer = _BitBuffer()
    buffer.put(0b0100, 4)                                   # mode octet
    buffer.put(len(payload), 8 if version < 10 else 16)     # longueur
    for byte in payload:
        buffer.put(byte, 8)

    capacity_bits = total_data * 8
    if len(buffer) > capacity_bits:
        raise ValueError("Débordement de capacité du QR code.")

    buffer.put(0, min(4, capacity_bits - len(buffer)))      # terminateur
    while len(buffer) % 8:
        buffer.bits.append(0)

    data = [int("".join(map(str, buffer.bits[i:i + 8])), 2)
            for i in range(0, len(buffer), 8)]
    # Remplissage alterné imposé par la norme
    pad = [0xEC, 0x11]
    while len(data) < total_data:
        data.append(pad[(len(data) - len(buffer) // 8) % 2])

    # Découpage en blocs, correction, puis entrelacement
    blocks: list[list[int]] = []
    offset = 0
    for count, size in ((g1, d1), (g2, d2)):
        for _ in range(count):
            blocks.append(data[offset:offset + size])
            offset += size
    ec_blocks = [_rs_encode(block, ec) for block in blocks]

    out: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec):
        for block in ec_blocks:
            out.append(block[i])
    return out


# ------------------------------------------------------------- construction
class QRCode:
    """Matrice de modules : ``matrix[y][x]`` vaut True pour un module noir."""

    def __init__(self, text: str, level: str = "M"):
        self.text = text
        self.version, self.level = _choose_version(
            len(text.encode("utf-8")), level)
        self.size = 17 + 4 * self.version
        self.matrix = [[None] * self.size for _ in range(self.size)]
        self._reserved = [[False] * self.size for _ in range(self.size)]
        self._build()

    # ------------------------------------------------------- motifs fixes
    def _place_finder(self, row: int, col: int) -> None:
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                y, x = row + dy, col + dx
                if not (0 <= y < self.size and 0 <= x < self.size):
                    continue
                inside = (0 <= dy <= 6 and 0 <= dx <= 6)
                dark = inside and (
                    dy in (0, 6) or dx in (0, 6)
                    or (2 <= dy <= 4 and 2 <= dx <= 4))
                self.matrix[y][x] = dark
                self._reserved[y][x] = True

    def _place_alignment(self) -> None:
        centers = _ALIGNMENT[self.version]
        for row in centers:
            for col in centers:
                # Les coins occupés par les motifs de détection sont exclus
                if (row, col) in ((6, 6), (6, centers[-1]), (centers[-1], 6)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        y, x = row + dy, col + dx
                        dark = max(abs(dy), abs(dx)) != 1
                        self.matrix[y][x] = dark
                        self._reserved[y][x] = True

    def _place_timing(self) -> None:
        for i in range(8, self.size - 8):
            dark = (i % 2 == 0)
            if not self._reserved[6][i]:
                self.matrix[6][i] = dark
                self._reserved[6][i] = True
            if not self._reserved[i][6]:
                self.matrix[i][6] = dark
                self._reserved[i][6] = True

    def _reserve_format(self) -> None:
        for i in range(9):
            if not self._reserved[8][i]:
                self._reserved[8][i] = True
                self.matrix[8][i] = False
            if not self._reserved[i][8]:
                self._reserved[i][8] = True
                self.matrix[i][8] = False
        for i in range(8):
            self._reserved[8][self.size - 1 - i] = True
            self.matrix[8][self.size - 1 - i] = False
            self._reserved[self.size - 1 - i][8] = True
            self.matrix[self.size - 1 - i][8] = False
        # Module toujours noir, imposé par la norme
        self.matrix[self.size - 8][8] = True
        self._reserved[self.size - 8][8] = True

        if self.version >= 7:
            for i in range(6):
                for j in range(3):
                    self._reserved[self.size - 11 + j][i] = True
                    self._reserved[i][self.size - 11 + j] = True

    # --------------------------------------------------------- placement
    def _place_data(self, codewords: list[int]) -> None:
        bits = [(byte >> i) & 1 for byte in codewords for i in range(7, -1, -1)]
        index = 0
        upward = True
        col = self.size - 1
        while col > 0:
            if col == 6:        # colonne de synchronisation verticale
                col -= 1
            rows = range(self.size - 1, -1, -1) if upward else range(self.size)
            for row in rows:
                for offset in (0, 1):
                    x = col - offset
                    if self._reserved[row][x]:
                        continue
                    self.matrix[row][x] = bool(bits[index]) if index < len(bits) else False
                    index += 1
            upward = not upward
            col -= 2

    # ---------------------------------------------------------- masquage
    @staticmethod
    def _mask_condition(mask: int, row: int, col: int) -> bool:
        if mask == 0: return (row + col) % 2 == 0
        if mask == 1: return row % 2 == 0
        if mask == 2: return col % 3 == 0
        if mask == 3: return (row + col) % 3 == 0
        if mask == 4: return (row // 2 + col // 3) % 2 == 0
        if mask == 5: return (row * col) % 2 + (row * col) % 3 == 0
        if mask == 6: return ((row * col) % 2 + (row * col) % 3) % 2 == 0
        return ((row + col) % 2 + (row * col) % 3) % 2 == 0

    def _apply_mask(self, mask: int) -> list[list[bool]]:
        out = [row[:] for row in self.matrix]
        for row in range(self.size):
            for col in range(self.size):
                if not self._reserved[row][col] and self._mask_condition(mask, row, col):
                    out[row][col] = not out[row][col]
        return out

    @staticmethod
    def _penalty(matrix: list[list[bool]]) -> int:
        """Score de pénalité de la norme : plus il est bas, mieux le code se lit."""
        size = len(matrix)
        score = 0

        # Règle 1 : suites de cinq modules identiques ou plus
        for line in list(matrix) + [list(col) for col in zip(*matrix)]:
            run, previous = 1, line[0]
            for value in line[1:]:
                if value == previous:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run, previous = 1, value
            if run >= 5:
                score += 3 + (run - 5)

        # Règle 2 : blocs 2×2 de même couleur
        for row in range(size - 1):
            for col in range(size - 1):
                block = (matrix[row][col], matrix[row][col + 1],
                         matrix[row + 1][col], matrix[row + 1][col + 1])
                if all(block) or not any(block):
                    score += 3

        # Règle 3 : motif ressemblant à un motif de détection
        patterns = ([True, False, True, True, True, False, True,
                     False, False, False, False],
                    [False, False, False, False, True, False, True,
                     True, True, False, True])
        for line in list(matrix) + [list(col) for col in zip(*matrix)]:
            for i in range(size - 10):
                window = line[i:i + 11]
                if window == patterns[0] or window == patterns[1]:
                    score += 40

        # Règle 4 : déséquilibre entre modules clairs et sombres
        dark = sum(sum(1 for v in row if v) for row in matrix)
        ratio = dark * 100 // (size * size)
        score += 10 * min(abs(ratio - 50) // 5, abs(ratio - 50 + 4) // 5)
        return score

    # --------------------------------------------- informations de format
    def _format_bits(self, mask: int) -> int:
        data = (_EC_BITS[self.level] << 3) | mask
        value = data << 10
        generator = 0b10100110111
        for i in range(4, -1, -1):
            if value & (1 << (i + 10)):
                value ^= generator << i
        return ((data << 10) | value) ^ 0b101010000010010

    @staticmethod
    def _version_bits(version: int) -> int:
        value = version << 12
        generator = 0b1111100100101
        for i in range(5, -1, -1):
            if value & (1 << (i + 12)):
                value ^= generator << i
        return (version << 12) | value

    def _write_format(self, matrix: list[list[bool]], mask: int) -> None:
        bits = self._format_bits(mask)
        for i in range(15):
            bit = bool((bits >> i) & 1)
            # Première copie, autour du motif supérieur gauche
            if i < 6:
                matrix[i][8] = bit
            elif i == 6:
                matrix[7][8] = bit
            elif i == 7:
                matrix[8][8] = bit
            elif i == 8:
                matrix[8][7] = bit
            else:
                matrix[8][14 - i] = bit
            # Seconde copie, répartie sur les deux autres coins
            if i < 8:
                matrix[8][self.size - 1 - i] = bit
            else:
                matrix[self.size - 15 + i][8] = bit

        if self.version >= 7:
            vbits = self._version_bits(self.version)
            for i in range(18):
                bit = bool((vbits >> i) & 1)
                row, col = i // 3, i % 3
                matrix[self.size - 11 + col][row] = bit
                matrix[row][self.size - 11 + col] = bit

    # ------------------------------------------------------------- montage
    def _build(self) -> None:
        self._place_finder(0, 0)
        self._place_finder(0, self.size - 7)
        self._place_finder(self.size - 7, 0)
        self._place_alignment()
        self._place_timing()
        self._reserve_format()
        self._place_data(_encode_data(self.text, self.version, self.level))

        best, best_score = None, None
        for mask in range(8):
            candidate = self._apply_mask(mask)
            self._write_format(candidate, mask)
            score = self._penalty(candidate)
            if best_score is None or score < best_score:
                best, best_score = candidate, score
                self.mask = mask
        self.matrix = best

    # ------------------------------------------------------------- rendus
    def to_text(self, quiet: int = 2) -> str:
        """Rendu pour un terminal, deux lignes de modules par ligne de texte.

        Les demi-blocs Unicode ▀ et ▄ donnent des modules carrés : un
        caractère de terminal est deux fois plus haut que large.
        """
        size = self.size
        grid = [[False] * (size + 2 * quiet) for _ in range(quiet)]
        for row in self.matrix:
            grid.append([False] * quiet + list(row) + [False] * quiet)
        grid += [[False] * (size + 2 * quiet) for _ in range(quiet)]
        if len(grid) % 2:
            grid.append([False] * len(grid[0]))

        lines = []
        for y in range(0, len(grid), 2):
            line = []
            for x in range(len(grid[0])):
                top, bottom = grid[y][x], grid[y + 1][x]
                # Convention : un module « noir » du QR doit apparaître
                # sombre. Sur fond de terminal clair comme sombre, les
                # lecteurs attendent du contraste, pas une couleur précise.
                if top and bottom:
                    line.append("█")
                elif top:
                    line.append("▀")
                elif bottom:
                    line.append("▄")
                else:
                    line.append(" ")
            lines.append("".join(line))
        return "\n".join(lines)

    def to_ascii(self, quiet: int = 2) -> str:
        """Rendu de secours en ASCII pur, deux caractères par module.

        Les demi-blocs de ``to_text`` ne s'affichent pas partout : certaines
        consoles Windows anciennes, et toute sortie redirigée vers un fichier
        en encodage ancien, lèvent une erreur ou impriment des « ? ». Ce
        rendu ne tient que sur des espaces et des dièses, donc il passe
        partout ; il occupe deux fois plus de lignes.
        """
        width = self.size + 2 * quiet
        lines = ["  " * width] * quiet
        for row in self.matrix:
            lines.append("  " * quiet
                         + "".join("##" if cell else "  " for cell in row)
                         + "  " * quiet)
        lines += ["  " * width] * quiet
        return "\n".join(lines)

    def to_svg(self, module: int = 8, quiet: int = 3,
               dark: str = "#000000", light: str = "#ffffff") -> str:
        """Rendu vectoriel, pour affichage dans l'interface."""
        span = (self.size + 2 * quiet) * module
        paths = []
        for y, row in enumerate(self.matrix):
            x = 0
            while x < self.size:
                if row[x]:
                    start = x
                    while x < self.size and row[x]:
                        x += 1
                    paths.append(
                        f"M{(start + quiet) * module} {(y + quiet) * module}"
                        f"h{(x - start) * module}v{module}h-{(x - start) * module}z")
                else:
                    x += 1
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{span}" '
                f'height="{span}" viewBox="0 0 {span} {span}" '
                f'shape-rendering="crispEdges" role="img" '
                f'aria-label="QR code vers {self.text}">'
                f'<rect width="{span}" height="{span}" fill="{light}"/>'
                f'<path d="{"".join(paths)}" fill="{dark}"/></svg>')


def make(text: str, level: str = "M") -> QRCode:
    return QRCode(text, level)


def terminal(text: str, level: str = "M") -> str:
    return QRCode(text, level).to_text()


def terminal_ascii(text: str, level: str = "M") -> str:
    return QRCode(text, level).to_ascii()


def svg(text: str, **kwargs) -> str:
    return QRCode(text, kwargs.pop("level", "M")).to_svg(**kwargs)
