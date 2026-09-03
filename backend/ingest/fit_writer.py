"""Encodeur FIT minimal.

Sert à deux choses : valider le décodeur par aller-retour, et produire des
fichiers ``.fit`` d'exemple réalistes que l'on peut réimporter dans
l'application pour éprouver la chaîne complète sans posséder de montre.

Seul le sous-ensemble nécessaire à un fichier d'activité est implémenté :
``file_id``, ``record``, ``lap`` et ``session``.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from io import BytesIO
from typing import Sequence

from .fit import (FIT_EPOCH, LAP_FIELDS, RECORD_FIELDS, SESSION_FIELDS,
                  fit_crc)

# type de base -> (code FIT, format struct, taille, valeur invalide)
T_UINT8 = (0x02, "B", 1, 0xFF)
T_UINT16 = (0x84, "H", 2, 0xFFFF)
T_UINT32 = (0x86, "I", 4, 0xFFFFFFFF)
T_SINT32 = (0x85, "i", 4, 0x7FFFFFFF)
T_SINT8 = (0x01, "b", 1, 0x7F)
T_ENUM = (0x00, "B", 1, 0xFF)


def to_fit_time(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - FIT_EPOCH).total_seconds())


def degrees_to_semicircles(deg: float | None) -> int | None:
    if deg is None:
        return None
    return int(round(deg * (2 ** 31 / 180.0)))


class FitWriter:
    """Construit un fichier FIT en mémoire."""

    def __init__(self):
        self.buf = BytesIO()
        self._locals: dict[int, tuple[int, list]] = {}
        self._next_local = 0

    # ------------------------------------------------------------ interne
    def _define(self, global_num: int, fields: Sequence[tuple[int, tuple]]) -> int:
        """Écrit un message de définition et renvoie son numéro local."""
        local = self._next_local % 16
        self._next_local += 1
        self.buf.write(struct.pack("<B", 0x40 | local))
        self.buf.write(struct.pack("<BBHB", 0, 0, global_num, len(fields)))
        for num, (base_code, _fmt, size, _inv) in fields:
            self.buf.write(struct.pack("<BBB", num, size, base_code))
        self._locals[local] = (global_num, list(fields))
        return local

    def _data(self, local: int, values: Sequence) -> None:
        _global, fields = self._locals[local]
        self.buf.write(struct.pack("<B", local & 0x0F))
        for (_num, (_code, fmt, _size, invalid)), value in zip(fields, values):
            if value is None:
                self.buf.write(struct.pack("<" + fmt, invalid))
            else:
                self.buf.write(struct.pack("<" + fmt, int(value)))

    @staticmethod
    def _encode(profile: dict, name: str, value):
        """Applique l'échelle et l'offset inverses du profil FIT."""
        for num, (fname, scale, offset, _u) in profile.items():
            if fname == name:
                if value is None:
                    return num, None
                return num, int(round((value + offset) * scale))
        raise KeyError(name)

    # ------------------------------------------------------------- messages
    def write_file_id(self, time_created: datetime, manufacturer: int = 1,
                      product: int = 3121, serial: int = 3141592653) -> None:
        fields = [(0, T_ENUM), (1, T_UINT16), (2, T_UINT16),
                  (3, T_UINT32), (4, T_UINT32)]
        local = self._define(0, fields)
        self._data(local, [4, manufacturer, product, serial,
                           to_fit_time(time_created)])   # type 4 = activity

    def write_records(self, start: datetime, streams: dict[str, Sequence]) -> None:
        """Écrit un message ``record`` par seconde."""
        names = [n for n in ("heart_rate", "power", "cadence", "speed",
                             "distance", "altitude", "temperature")
                 if n in streams]
        has_gps = "lat" in streams and "lon" in streams
        types = {"heart_rate": T_UINT8, "power": T_UINT16, "cadence": T_UINT8,
                 "speed": T_UINT16, "distance": T_UINT32,
                 "altitude": T_UINT16, "temperature": T_SINT8}
        fields = [(253, T_UINT32)]
        if has_gps:
            fields += [(0, T_SINT32), (1, T_SINT32)]
        for n in names:
            num = next(k for k, v in RECORD_FIELDS.items() if v[0] == n)
            fields.append((num, types[n]))
        local = self._define(20, fields)

        t0 = to_fit_time(start)
        n_samples = max(len(streams[n]) for n in names) if names else 0
        for i in range(n_samples):
            row = [t0 + i]
            if has_gps:
                row += [degrees_to_semicircles(streams["lat"][i]),
                        degrees_to_semicircles(streams["lon"][i])]
            for n in names:
                value = streams[n][i] if i < len(streams[n]) else None
                if value is None:
                    row.append(None)
                else:
                    _num, encoded = self._encode(RECORD_FIELDS, n, value)
                    row.append(encoded)
            self._data(local, row)

    def write_lap(self, start: datetime, duration_s: float, distance_m: float,
                  avg_hr=None, max_hr=None, avg_power=None, avg_speed=None,
                  avg_cadence=None, ascent=None) -> None:
        fields = [(253, T_UINT32), (2, T_UINT32), (7, T_UINT32), (8, T_UINT32),
                  (9, T_UINT32), (13, T_UINT16), (15, T_UINT8), (16, T_UINT8),
                  (17, T_UINT8), (19, T_UINT16), (21, T_UINT16)]
        local = self._define(19, fields)
        enc = lambda n, v: self._encode(LAP_FIELDS, n, v)[1]
        self._data(local, [
            to_fit_time(start) + int(duration_s), to_fit_time(start),
            enc("total_elapsed_time", duration_s),
            enc("total_timer_time", duration_s),
            enc("total_distance", distance_m),
            enc("avg_speed", avg_speed), avg_hr, max_hr, avg_cadence,
            avg_power, ascent,
        ])

    def write_session(self, start: datetime, duration_s: float, distance_m: float,
                      sport: int = 1, sub_sport: int = 0, avg_hr=None, max_hr=None,
                      avg_power=None, max_power=None, np=None, avg_speed=None,
                      max_speed=None, avg_cadence=None, calories=None,
                      ascent=None, descent=None, start_lat=None,
                      start_lon=None) -> None:
        fields = [(253, T_UINT32), (2, T_UINT32), (3, T_SINT32), (4, T_SINT32),
                  (5, T_ENUM), (6, T_ENUM), (7, T_UINT32), (8, T_UINT32),
                  (9, T_UINT32), (11, T_UINT16), (14, T_UINT16), (15, T_UINT16),
                  (16, T_UINT8), (17, T_UINT8), (18, T_UINT8), (20, T_UINT16),
                  (21, T_UINT16), (22, T_UINT16), (23, T_UINT16), (34, T_UINT16)]
        local = self._define(18, fields)
        enc = lambda n, v: self._encode(SESSION_FIELDS, n, v)[1]
        self._data(local, [
            to_fit_time(start) + int(duration_s), to_fit_time(start),
            degrees_to_semicircles(start_lat), degrees_to_semicircles(start_lon),
            sport, sub_sport,
            enc("total_elapsed_time", duration_s),
            enc("total_timer_time", duration_s),
            enc("total_distance", distance_m),
            calories,
            enc("avg_speed", avg_speed), enc("max_speed", max_speed),
            avg_hr, max_hr, avg_cadence, avg_power, max_power,
            ascent, descent, np,
        ])

    # --------------------------------------------------------------- sortie
    def build(self) -> bytes:
        data = self.buf.getvalue()
        header = struct.pack("<BBHI4s", 12, 0x20, 2140, len(data), b".FIT")
        crc = fit_crc(data, fit_crc(header))
        return header + data + struct.pack("<H", crc)

    def save(self, path) -> int:
        blob = self.build()
        with open(path, "wb") as fh:
            fh.write(blob)
        return len(blob)
