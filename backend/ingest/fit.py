"""Décodeur FIT (Flexible and Interoperable Data Transfer) écrit de zéro.

Le FIT est le format natif de Garmin, également exporté par Polar (Flow) et
Coros (application et API). Décoder ce format sans dépendance externe est ce
qui permet d'importer les fichiers des trois marques avec un seul chemin de
code.

Structure du fichier
--------------------
    [en-tête 12 ou 14 octets]
    [suite d'enregistrements]
    [CRC 2 octets]

En-tête : taille(1) · version protocole(1) · version profil(2 LE) ·
taille données(4 LE) · « .FIT »(4) · [CRC(2)]

Chaque enregistrement commence par un octet d'en-tête :
  * bit 7 = 0 → en-tête normal
        bit 6 : 1 = message de définition, 0 = message de données
        bit 5 : présence de champs développeur (définition)
        bits 0-3 : numéro de message local (0-15)
  * bit 7 = 1 → en-tête à horodatage compressé
        bits 5-6 : message local · bits 0-4 : offset de temps (0-31 s)

Un message de définition décrit la structure binaire des messages de données
qui suivront pour le même numéro local : architecture (petit/gros boutiste),
numéro de message global, puis pour chaque champ (numéro, taille, type de base).

Les valeurs sont stockées en entiers mis à l'échelle : la valeur physique
vaut ``brut / scale − offset``. Les valeurs « invalides » (0xFF, 0xFFFF…)
signalent une donnée absente et sont converties en ``None``.
"""
from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO, Iterator

# Époque FIT : 31 décembre 1989 à 00:00:00 UTC
FIT_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

# type de base -> (format struct, taille, valeur invalide, est_numérique)
BASE_TYPES: dict[int, tuple[str, int, Any, bool]] = {
    0x00: ("B", 1, 0xFF, True),                  # enum
    0x01: ("b", 1, 0x7F, True),                  # sint8
    0x02: ("B", 1, 0xFF, True),                  # uint8
    0x83: ("h", 2, 0x7FFF, True),                # sint16
    0x84: ("H", 2, 0xFFFF, True),                # uint16
    0x85: ("i", 4, 0x7FFFFFFF, True),            # sint32
    0x86: ("I", 4, 0xFFFFFFFF, True),            # uint32
    0x07: ("s", 1, 0x00, False),                 # string
    0x88: ("f", 4, 0xFFFFFFFF, True),            # float32
    0x89: ("d", 8, 0xFFFFFFFFFFFFFFFF, True),    # float64
    0x0A: ("B", 1, 0x00, True),                  # uint8z
    0x8B: ("H", 2, 0x0000, True),                # uint16z
    0x8C: ("I", 4, 0x00000000, True),            # uint32z
    0x0D: ("B", 1, 0xFF, False),                 # byte
    0x8E: ("q", 8, 0x7FFFFFFFFFFFFFFF, True),    # sint64
    0x8F: ("Q", 8, 0xFFFFFFFFFFFFFFFF, True),    # uint64
    0x90: ("Q", 8, 0x0000000000000000, True),    # uint64z
}

# ------------------------------------------------------------ profil FIT
# (numéro de champ) -> (nom, échelle, offset, unité)
RECORD_FIELDS = {
    253: ("timestamp", 1, 0, "s"),
    0: ("position_lat", 1, 0, "semicircles"),
    1: ("position_long", 1, 0, "semicircles"),
    2: ("altitude", 5, 500, "m"),
    3: ("heart_rate", 1, 0, "bpm"),
    4: ("cadence", 1, 0, "rpm"),
    5: ("distance", 100, 0, "m"),
    6: ("speed", 1000, 0, "m/s"),
    7: ("power", 1, 0, "W"),
    9: ("grade", 100, 0, "%"),
    13: ("temperature", 1, 0, "C"),
    30: ("left_right_balance", 1, 0, "%"),
    39: ("vertical_oscillation", 10, 0, "mm"),
    40: ("stance_time_percent", 100, 0, "%"),
    41: ("stance_time", 10, 0, "ms"),
    53: ("fractional_cadence", 128, 0, "rpm"),
    54: ("total_hemoglobin_conc", 100, 0, "g/dL"),
    57: ("saturated_hemoglobin_percent", 10, 0, "%"),
    61: ("device_index", 1, 0, ""),
    73: ("enhanced_speed", 1000, 0, "m/s"),
    78: ("enhanced_altitude", 5, 500, "m"),
    83: ("vertical_ratio", 100, 0, "%"),
    84: ("stance_time_balance", 100, 0, "%"),
    85: ("step_length", 10, 0, "mm"),
    108: ("respiration_rate", 100, 0, "brpm"),
}

SESSION_FIELDS = {
    253: ("timestamp", 1, 0, "s"),
    2: ("start_time", 1, 0, "s"),
    3: ("start_position_lat", 1, 0, "semicircles"),
    4: ("start_position_long", 1, 0, "semicircles"),
    5: ("sport", 1, 0, ""),
    6: ("sub_sport", 1, 0, ""),
    7: ("total_elapsed_time", 1000, 0, "s"),
    8: ("total_timer_time", 1000, 0, "s"),
    9: ("total_distance", 100, 0, "m"),
    10: ("total_cycles", 1, 0, ""),
    11: ("total_calories", 1, 0, "kcal"),
    14: ("avg_speed", 1000, 0, "m/s"),
    15: ("max_speed", 1000, 0, "m/s"),
    16: ("avg_heart_rate", 1, 0, "bpm"),
    17: ("max_heart_rate", 1, 0, "bpm"),
    18: ("avg_cadence", 1, 0, "rpm"),
    19: ("max_cadence", 1, 0, "rpm"),
    20: ("avg_power", 1, 0, "W"),
    21: ("max_power", 1, 0, "W"),
    22: ("total_ascent", 1, 0, "m"),
    23: ("total_descent", 1, 0, "m"),
    24: ("total_training_effect", 10, 0, ""),
    34: ("normalized_power", 1, 0, "W"),
    35: ("training_stress_score", 10, 0, ""),
    36: ("intensity_factor", 1000, 0, ""),
    48: ("total_work", 1, 0, "J"),
    57: ("avg_temperature", 1, 0, "C"),
    58: ("max_temperature", 1, 0, "C"),
    89: ("avg_vertical_oscillation", 10, 0, "mm"),
    91: ("avg_stance_time", 10, 0, "ms"),
    99: ("avg_step_length", 10, 0, "mm"),
    124: ("enhanced_avg_speed", 1000, 0, "m/s"),
    125: ("enhanced_max_speed", 1000, 0, "m/s"),
    137: ("total_anaerobic_training_effect", 10, 0, ""),
}

LAP_FIELDS = {
    253: ("timestamp", 1, 0, "s"),
    2: ("start_time", 1, 0, "s"),
    7: ("total_elapsed_time", 1000, 0, "s"),
    8: ("total_timer_time", 1000, 0, "s"),
    9: ("total_distance", 100, 0, "m"),
    11: ("total_calories", 1, 0, "kcal"),
    13: ("avg_speed", 1000, 0, "m/s"),
    14: ("max_speed", 1000, 0, "m/s"),
    15: ("avg_heart_rate", 1, 0, "bpm"),
    16: ("max_heart_rate", 1, 0, "bpm"),
    17: ("avg_cadence", 1, 0, "rpm"),
    18: ("max_cadence", 1, 0, "rpm"),
    19: ("avg_power", 1, 0, "W"),
    20: ("max_power", 1, 0, "W"),
    21: ("total_ascent", 1, 0, "m"),
    22: ("total_descent", 1, 0, "m"),
    23: ("intensity", 1, 0, ""),
    24: ("lap_trigger", 1, 0, ""),
    25: ("sport", 1, 0, ""),
}

FILE_ID_FIELDS = {
    0: ("type", 1, 0, ""),
    1: ("manufacturer", 1, 0, ""),
    2: ("product", 1, 0, ""),
    3: ("serial_number", 1, 0, ""),
    4: ("time_created", 1, 0, "s"),
    8: ("product_name", 1, 0, ""),
}

DEVICE_INFO_FIELDS = {
    253: ("timestamp", 1, 0, "s"),
    0: ("device_index", 1, 0, ""),
    1: ("device_type", 1, 0, ""),
    2: ("manufacturer", 1, 0, ""),
    3: ("serial_number", 1, 0, ""),
    4: ("product", 1, 0, ""),
    5: ("software_version", 100, 0, ""),
    10: ("battery_voltage", 256, 0, "V"),
    27: ("product_name", 1, 0, ""),
}

MESSAGE_PROFILES = {
    0: ("file_id", FILE_ID_FIELDS),
    18: ("session", SESSION_FIELDS),
    19: ("lap", LAP_FIELDS),
    20: ("record", RECORD_FIELDS),
    21: ("event", {253: ("timestamp", 1, 0, "s"), 0: ("event", 1, 0, ""),
                   1: ("event_type", 1, 0, ""), 4: ("data", 1, 0, "")}),
    23: ("device_info", DEVICE_INFO_FIELDS),
    34: ("activity", {253: ("timestamp", 1, 0, "s"),
                      0: ("total_timer_time", 1000, 0, "s"),
                      1: ("num_sessions", 1, 0, ""),
                      5: ("local_timestamp", 1, 0, "s")}),
}

SPORT_NAMES = {
    0: "generic", 1: "running", 2: "cycling", 3: "transition",
    4: "fitness_equipment", 5: "swimming", 6: "basketball", 7: "soccer",
    8: "tennis", 9: "american_football", 10: "training", 11: "walking",
    12: "cross_country_skiing", 13: "alpine_skiing", 14: "snowboarding",
    15: "rowing", 16: "mountaineering", 17: "hiking", 18: "multisport",
    19: "paddling", 20: "flying", 21: "e_biking", 22: "motorcycling",
    23: "boating", 24: "driving", 25: "golf", 26: "hang_gliding",
    27: "horseback_riding", 28: "hunting", 29: "fishing",
    30: "inline_skating", 31: "rock_climbing", 32: "sailing",
    33: "ice_skating", 34: "sky_diving", 35: "snowshoeing",
    36: "snowmobiling", 37: "stand_up_paddleboarding", 38: "surfing",
    39: "wakeboarding", 40: "water_skiing", 41: "kayaking", 42: "rafting",
    43: "windsurfing", 44: "kitesurfing", 45: "tactical", 46: "jumpmaster",
    47: "boxing", 48: "floor_climbing", 53: "diving",
}

SUB_SPORT_NAMES = {
    0: "generic", 1: "treadmill", 2: "street", 3: "trail", 4: "track",
    5: "spin", 6: "indoor_cycling", 7: "road", 8: "mountain", 9: "downhill",
    10: "recumbent", 11: "cyclocross", 12: "hand_cycling", 13: "track_cycling",
    14: "indoor_rowing", 15: "elliptical", 16: "stair_climbing",
    17: "lap_swimming", 18: "open_water", 19: "flexibility_training",
    20: "strength_training", 21: "warm_up", 22: "match", 23: "exercise",
    24: "challenge", 25: "indoor_skiing", 26: "cardio_training",
    27: "indoor_walking", 28: "e_bike_fitness", 29: "bmx",
}

MANUFACTURERS = {
    1: "Garmin", 2: "garmin_fr405", 3: "zephyr", 4: "dayton", 5: "idt",
    6: "srm", 7: "quarq", 8: "ibike", 9: "saris", 10: "spark_hk",
    11: "tanita", 12: "echowell", 13: "dynastream_oem", 14: "nautilus",
    15: "dynastream", 16: "timex", 17: "metrigear", 18: "xelic",
    23: "suunto", 32: "wahoo_fitness", 38: "Polar", 41: "cateye",
    54: "Coros", 60: "stages", 63: "specialized", 68: "bkool",
    69: "cannondale", 76: "moxy", 89: "tacx", 95: "elite",
    102: "wattbike", 260: "zwift", 263: "hammerhead", 265: "Coros",
    294: "Coros",
}


class FitError(Exception):
    """Fichier FIT illisible ou corrompu."""


# ------------------------------------------------------------------- CRC
CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
             0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)


def fit_crc(data: bytes, crc: int = 0) -> int:
    """CRC-16 du FIT SDK (table de 16 entrées, deux passes par octet)."""
    for byte in data:
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF]
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def fit_timestamp(value: int | None) -> datetime | None:
    if value is None:
        return None
    return FIT_EPOCH + timedelta(seconds=int(value))


def semicircles_to_degrees(value: int | None) -> float | None:
    """Les positions FIT sont en semicercles : deg = semicercles × 180 / 2³¹."""
    if value is None:
        return None
    return round(value * (180.0 / 2 ** 31), 7)


class _FieldDef:
    __slots__ = ("num", "size", "base_type", "is_dev")

    def __init__(self, num: int, size: int, base_type: int, is_dev: bool = False):
        self.num = num
        self.size = size
        self.base_type = base_type
        self.is_dev = is_dev


class _MessageDef:
    __slots__ = ("global_num", "endian", "fields", "size")

    def __init__(self, global_num: int, endian: str, fields: list[_FieldDef]):
        self.global_num = global_num
        self.endian = endian
        self.fields = fields
        self.size = sum(f.size for f in fields)


class FitDecoder:
    """Décodeur en flux : produit des messages (nom, champs) au fil de la lecture."""

    def __init__(self, stream: BinaryIO, check_crc: bool = True):
        self.stream = stream
        self.check_crc = check_crc
        self.definitions: dict[int, _MessageDef] = {}
        self.dev_fields: dict[tuple[int, int], dict] = {}
        self.last_timestamp: int | None = None
        self.header: dict = {}
        self.unknown_messages: dict[int, int] = {}

    # ------------------------------------------------------------- en-tête
    def _read_header(self) -> int:
        raw = self.stream.read(12)
        if len(raw) < 12:
            raise FitError("Fichier trop court pour contenir un en-tête FIT.")
        size, proto, profile, data_size = struct.unpack("<BBHI", raw[:8])
        magic = raw[8:12]
        if magic != b".FIT":
            raise FitError(f"Signature « .FIT » absente (trouvé {magic!r}).")
        if size not in (12, 14):
            raise FitError(f"Taille d'en-tête inattendue : {size}.")
        if size == 14:
            self.stream.read(2)          # CRC de l'en-tête, non vérifié
        self.header = {
            "header_size": size,
            "protocol_version": f"{proto >> 4}.{proto & 0x0F}",
            "profile_version": f"{profile // 100}.{profile % 100}",
            "data_size": data_size,
        }
        return data_size

    # ------------------------------------------------------------ décodage
    def _read_definition(self, local: int, has_dev: bool) -> None:
        head = self.stream.read(5)
        if len(head) < 5:
            raise FitError("Message de définition tronqué.")
        _reserved, arch, global_num, n_fields = struct.unpack("<BBHB", head)
        endian = ">" if arch == 1 else "<"
        if arch == 1:
            global_num = struct.unpack(">H", struct.pack("<H", global_num))[0]
        fields: list[_FieldDef] = []
        for _ in range(n_fields):
            chunk = self.stream.read(3)
            if len(chunk) < 3:
                raise FitError("Définition de champ tronquée.")
            num, size, base = struct.unpack("<BBB", chunk)
            fields.append(_FieldDef(num, size, base))
        if has_dev:
            n_dev = self.stream.read(1)
            if n_dev:
                for _ in range(n_dev[0]):
                    chunk = self.stream.read(3)
                    if len(chunk) < 3:
                        break
                    num, size, _idx = struct.unpack("<BBB", chunk)
                    fields.append(_FieldDef(num, size, 0x0D, is_dev=True))
        self.definitions[local] = _MessageDef(global_num, endian, fields)

    def _read_value(self, field: _FieldDef, endian: str, raw: bytes) -> Any:
        base = BASE_TYPES.get(field.base_type & 0x9F)
        if base is None:
            base = BASE_TYPES[0x0D]
        fmt, unit_size, invalid, numeric = base

        if field.base_type in (0x07,):                 # chaîne
            text = raw.split(b"\x00")[0]
            try:
                return text.decode("utf-8") or None
            except UnicodeDecodeError:
                return None
        if field.base_type in (0x0D,) or not numeric:  # octets bruts
            return raw if any(raw) else None

        count = max(1, field.size // unit_size)
        try:
            values = struct.unpack(f"{endian}{count}{fmt}", raw[: count * unit_size])
        except struct.error:
            return None
        cleaned = [None if v == invalid else v for v in values]
        if len(cleaned) == 1:
            return cleaned[0]
        return cleaned if any(v is not None for v in cleaned) else None

    def _read_data(self, local: int, time_offset: int | None = None) -> tuple[str, dict] | None:
        definition = self.definitions.get(local)
        if definition is None:
            raise FitError(f"Message de données {local} sans définition préalable.")
        payload = self.stream.read(definition.size)
        if len(payload) < definition.size:
            return None

        name, profile = MESSAGE_PROFILES.get(
            definition.global_num, (f"msg_{definition.global_num}", {}))
        if definition.global_num not in MESSAGE_PROFILES:
            self.unknown_messages[definition.global_num] = \
                self.unknown_messages.get(definition.global_num, 0) + 1

        out: dict[str, Any] = {}
        pos = 0
        for field in definition.fields:
            raw = payload[pos:pos + field.size]
            pos += field.size
            value = self._read_value(field, definition.endian, raw)
            if value is None:
                continue
            if field.is_dev:
                out[f"dev_{field.num}"] = value
                continue
            meta = profile.get(field.num)
            if meta is None:
                out[f"field_{field.num}"] = value
                continue
            fname, scale, offset, _unit = meta
            if isinstance(value, (int, float)) and (scale != 1 or offset != 0):
                value = value / scale - offset
            out[fname] = value

        # horodatage compressé : on reconstitue depuis le dernier timestamp connu
        if time_offset is not None and self.last_timestamp is not None:
            rolled = (self.last_timestamp & ~0x1F) | time_offset
            if rolled < self.last_timestamp:
                rolled += 0x20
            out["timestamp"] = rolled
            self.last_timestamp = rolled
        elif "timestamp" in out and isinstance(out["timestamp"], (int, float)):
            self.last_timestamp = int(out["timestamp"])
        return name, out

    def messages(self) -> Iterator[tuple[str, dict]]:
        """Itère sur tous les messages du fichier."""
        data_size = self._read_header()
        consumed = 0
        while consumed < data_size:
            head = self.stream.read(1)
            if not head:
                break
            consumed += 1
            byte = head[0]
            start = self.stream.tell()

            if byte & 0x80:                              # horodatage compressé
                local = (byte >> 5) & 0x03
                offset = byte & 0x1F
                result = self._read_data(local, offset)
            elif byte & 0x40:                            # définition
                self._read_definition(local=byte & 0x0F, has_dev=bool(byte & 0x20))
                result = None
            else:                                        # données
                result = self._read_data(byte & 0x0F)

            consumed += self.stream.tell() - start
            if result is not None:
                yield result


def decode(path_or_stream, check_crc: bool = True) -> dict:
    """Décode un fichier FIT complet et regroupe les messages par type.

    Renvoie ``{"header": …, "records": [...], "sessions": [...],
    "laps": [...], "file_id": {...}, "devices": [...], "events": [...]}``.
    """
    close_after = False
    if hasattr(path_or_stream, "read"):
        stream = path_or_stream
    else:
        stream = open(path_or_stream, "rb")
        close_after = True
    try:
        decoder = FitDecoder(stream, check_crc=check_crc)
        out: dict[str, Any] = {
            "records": [], "sessions": [], "laps": [], "events": [],
            "devices": [], "file_id": {}, "activity": {}, "other": {},
        }
        for name, msg in decoder.messages():
            if name == "record":
                out["records"].append(msg)
            elif name == "session":
                out["sessions"].append(msg)
            elif name == "lap":
                out["laps"].append(msg)
            elif name == "event":
                out["events"].append(msg)
            elif name == "device_info":
                out["devices"].append(msg)
            elif name == "file_id":
                out["file_id"] = msg
            elif name == "activity":
                out["activity"] = msg
            else:
                out["other"].setdefault(name, []).append(msg)
        out["header"] = decoder.header
        out["unknown_messages"] = decoder.unknown_messages
        return out
    finally:
        if close_after:
            stream.close()


def to_streams(records: list[dict]) -> dict[str, list]:
    """Convertit les messages ``record`` en séries temporelles alignées à 1 Hz.

    Les montres n'échantillonnent pas toujours à intervalle fixe (mode
    « smart recording » de Garmin) : on ré-échantillonne à la seconde par
    maintien de la dernière valeur, ce qui est nécessaire pour que les
    moyennes glissantes (NP, courbe record) aient un sens temporel.
    """
    stamped = [r for r in records if r.get("timestamp") is not None]
    if not stamped:
        return {}
    stamped.sort(key=lambda r: r["timestamp"])
    t0 = int(stamped[0]["timestamp"])
    t1 = int(stamped[-1]["timestamp"])
    span = t1 - t0 + 1
    if span <= 0 or span > 86400 * 2:
        span = len(stamped)

    keys = ("heart_rate", "power", "cadence", "temperature",
            "vertical_oscillation", "stance_time", "step_length",
            "respiration_rate")
    series: dict[str, list] = {k: [None] * span for k in keys}
    series["speed"] = [None] * span
    series["altitude"] = [None] * span
    series["distance"] = [None] * span
    series["lat"] = [None] * span
    series["lon"] = [None] * span

    for r in stamped:
        i = int(r["timestamp"]) - t0
        if not (0 <= i < span):
            continue
        for k in keys:
            if r.get(k) is not None:
                series[k][i] = r[k]
        speed = r.get("enhanced_speed", r.get("speed"))
        if speed is not None:
            series["speed"][i] = speed
        alt = r.get("enhanced_altitude", r.get("altitude"))
        if alt is not None:
            series["altitude"][i] = alt
        if r.get("distance") is not None:
            series["distance"][i] = r["distance"]
        if r.get("position_lat") is not None:
            series["lat"][i] = semicircles_to_degrees(r["position_lat"])
        if r.get("position_long") is not None:
            series["lon"][i] = semicircles_to_degrees(r["position_long"])

    # maintien de la dernière valeur sur les trous courts (< 30 s)
    for key, values in series.items():
        last_idx = None
        for i, v in enumerate(values):
            if v is not None:
                if last_idx is not None and i - last_idx <= 30:
                    prev = values[last_idx]
                    gap = i - last_idx
                    for j in range(1, gap):     # interpolation linéaire
                        values[last_idx + j] = prev + (v - prev) * j / gap
                last_idx = i
    series["time"] = list(range(span))
    return {k: v for k, v in series.items() if any(x is not None for x in v)}
