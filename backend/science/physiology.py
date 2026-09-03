"""Estimations physiologiques et besoins énergétiques.

Regroupe les formules de terrain qui permettent de renseigner un profil
d'athlète sans laboratoire, en indiquant systématiquement l'erreur type
associée : ces estimations orientent, elles ne remplacent pas une mesure.
"""
from __future__ import annotations

import math

# ------------------------------------------------------------ FC maximale
HRMAX_FORMULAS = {
    "fox": ("Fox (1971) : 220 − âge", lambda age, sex: 220 - age, 11.0),
    "tanaka": ("Tanaka (2001) : 208 − 0,7 × âge", lambda age, sex: 208 - 0.7 * age, 7.0),
    "gellish": ("Gellish (2007) : 207 − 0,7 × âge", lambda age, sex: 207 - 0.7 * age, 6.5),
    "nes": ("Nes (2013) : 211 − 0,64 × âge", lambda age, sex: 211 - 0.64 * age, 6.8),
    "gulati": ("Gulati (2010, femmes) : 206 − 0,88 × âge",
               lambda age, sex: 206 - 0.88 * age, 6.0),
}


def estimate_hr_max(age: float, sex: str = "X", formula: str = "tanaka") -> dict | None:
    """FC max estimée. Tanaka par défaut (moins biaisée que 220 − âge)."""
    if not age or age <= 0:
        return None
    if sex == "F" and formula == "tanaka":
        formula = "gulati"
    label, fn, sem = HRMAX_FORMULAS.get(formula, HRMAX_FORMULAS["tanaka"])
    value = fn(age, sex)
    return {
        "hr_max": round(value),
        "formula": label,
        "sem_bpm": sem,
        "range": [round(value - 2 * sem), round(value + 2 * sem)],
        "caveat": "Erreur type de 6 à 11 bpm selon la formule : une mesure "
                  "de terrain (test progressif maximal) reste très supérieure.",
    }


# ---------------------------------------------------------------- VO2max
def vo2max_uth_sorensen(hr_max: float, hr_rest: float) -> float | None:
    """Uth-Sørensen-Overgaard-Pedersen (2004) : VO2max ≈ 15,3 × FCmax/FCrepos.
    Validé sur des sujets entraînés, erreur type ~10 %."""
    if not hr_max or not hr_rest or hr_rest <= 0:
        return None
    return round(15.3 * (hr_max / hr_rest), 1)


def vo2max_cooper(distance_m: float) -> float | None:
    """Test de Cooper (12 min) : VO2max = (d − 504,9) / 44,73."""
    if not distance_m or distance_m < 1000:
        return None
    return round((distance_m - 504.9) / 44.73, 1)


def vo2max_from_vma(vma_ms: float) -> float | None:
    """VO2max ≈ 3,5 × VMA (km/h) — approximation classique de Léger-Mercier
    (coût énergétique de 3,5 ml/kg/min par km/h)."""
    if not vma_ms or vma_ms <= 0:
        return None
    return round(3.5 * vma_ms * 3.6, 1)


def vo2max_from_ftp(ftp_w: float, weight_kg: float) -> float | None:
    """Estimation cycliste : VO2max ≈ (10,8 × P/kg à VO2max + 7).
    La puissance à VO2max est prise à 1,20 × FTP (Coggan)."""
    if not ftp_w or not weight_kg or weight_kg <= 0:
        return None
    p_vo2 = ftp_w * 1.20
    return round((10.8 * p_vo2 / weight_kg) + 7.0, 1)


VO2MAX_NORMS = {   # (âge min, âge max) -> {sexe: [seuils excellent..faible]}
    (20, 29): {"M": [55.4, 51.1, 45.4, 41.7], "F": [49.6, 43.9, 39.5, 36.1]},
    (30, 39): {"M": [54.0, 48.3, 44.0, 40.5], "F": [47.4, 42.4, 37.8, 34.4]},
    (40, 49): {"M": [52.5, 46.4, 42.4, 38.5], "F": [45.3, 39.7, 36.3, 33.0]},
    (50, 59): {"M": [48.9, 43.4, 39.2, 35.6], "F": [41.1, 36.7, 33.0, 30.1]},
    (60, 99): {"M": [45.7, 39.5, 35.5, 32.3], "F": [37.8, 33.0, 30.9, 28.1]},
}
VO2MAX_LABELS = ["Supérieur", "Excellent", "Bon", "Moyen", "Faible"]


def vo2max_percentile(vo2: float, age: float, sex: str) -> str | None:
    """Situe une VO2max dans les normes ACSM par tranche d'âge."""
    if not vo2 or not age:
        return None
    for (lo, hi), table in VO2MAX_NORMS.items():
        if lo <= age <= hi:
            thresholds = table.get(sex if sex in table else "M")
            for i, t in enumerate(thresholds):
                if vo2 >= t:
                    return VO2MAX_LABELS[i]
            return VO2MAX_LABELS[-1]
    return None


# ---------------------------------------------------------- dépense d'énergie
def energy_from_power(work_kj: float, efficiency: float = 0.235) -> float | None:
    """Dépense (kcal) depuis le travail mécanique.

    Le rendement brut du pédalage est de 20 à 25 % ; à 23,5 %, le facteur de
    conversion kJ → kcal est ≈ 1,0, d'où l'usage cycliste courant
    « 1 kJ ≈ 1 kcal ».
    """
    if not work_kj:
        return None
    return round(work_kj / 4.184 / efficiency, 0)


def energy_from_hr(duration_s: float, avg_hr: float, weight_kg: float,
                   age: float, sex: str = "M") -> float | None:
    """Keytel et al. (2005) — dépense énergétique à partir de la FC."""
    if not all((duration_s, avg_hr, weight_kg, age)):
        return None
    minutes = duration_s / 60.0
    if sex == "F":
        kcal_min = (-20.4022 + 0.4472 * avg_hr - 0.1263 * weight_kg + 0.074 * age) / 4.184
    else:
        kcal_min = (-55.0969 + 0.6309 * avg_hr + 0.1988 * weight_kg + 0.2017 * age) / 4.184
    return round(max(0.0, kcal_min * minutes), 0)


def energy_running(distance_m: float, weight_kg: float,
                   elevation_gain_m: float = 0.0) -> float | None:
    """Course : ≈ 1 kcal par kg et par km sur le plat, plus le travail
    gravitaire du dénivelé (rendement de montée ≈ 25 %)."""
    if not distance_m or not weight_kg:
        return None
    flat = 0.98 * weight_kg * (distance_m / 1000.0)
    climb = (weight_kg * 9.81 * (elevation_gain_m or 0) / 0.25) / 4184.0
    return round(flat + climb, 0)


def bmr_mifflin(weight_kg: float, height_cm: float, age: float, sex: str = "M") -> float | None:
    """Métabolisme de base — Mifflin-St Jeor (1990)."""
    if not all((weight_kg, height_cm, age)):
        return None
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(base + (5 if sex == "M" else -161), 0)


def carb_needs(duration_s: float, intensity: str = "moderate") -> dict:
    """Apports glucidiques recommandés à l'effort (Jeukendrup 2014)."""
    hours = (duration_s or 0) / 3600.0
    if hours < 0.75:
        rate, note = 0, "Moins de 45 min : aucun apport nécessaire."
    elif hours < 1.25:
        rate, note = 20, "45–75 min : bain de bouche glucidique ou 20 g/h."
    elif hours < 2.5:
        rate, note = 45, "1–2,5 h : 30 à 60 g/h de glucides."
    elif hours < 3.0:
        rate, note = 65, "2,5–3 h : 60 g/h (glucose seul suffisant)."
    else:
        rate, note = 85, ("> 3 h : 80 à 110 g/h avec mélange glucose-fructose "
                          "(2:1) pour dépasser la saturation des transporteurs SGLT1.")
    return {
        "g_per_hour": rate,
        "total_g": round(rate * hours),
        "note": note,
        "fluid_ml_per_hour": 500 if hours >= 1 else 0,
        "sodium_mg_per_hour": 500 if hours >= 2 else 300,
    }


def sweat_rate(weight_before_kg: float, weight_after_kg: float,
               fluid_intake_ml: float, duration_s: float) -> dict | None:
    """Taux de sudation (L/h) = (Δ masse + boisson) / durée."""
    if None in (weight_before_kg, weight_after_kg, duration_s) or duration_s <= 0:
        return None
    loss_l = (weight_before_kg - weight_after_kg) + (fluid_intake_ml or 0) / 1000.0
    rate = loss_l / (duration_s / 3600.0)
    pct = 100 * (weight_before_kg - weight_after_kg) / weight_before_kg
    return {
        "sweat_rate_l_h": round(rate, 2),
        "dehydration_pct": round(pct, 2),
        "flag": ("perte hydrique > 2 % : performance aérobie altérée"
                 if pct > 2 else "déshydratation maîtrisée"),
        "replace_ml_h": round(rate * 1000 * 0.8),
    }


# ------------------------------------------------------ conditions externes
def altitude_vo2max_factor(altitude_m: float) -> float:
    """Perte de VO2max en altitude : ≈ 1 % par 100 m au-dessus de 1 500 m
    (Bassett et al., 1999)."""
    if altitude_m is None or altitude_m <= 1500:
        return 1.0
    return max(0.55, 1.0 - 0.01 * (altitude_m - 1500) / 100.0)


def heat_pace_penalty(temp_c: float, humidity_pct: float = 50.0) -> float:
    """Majoration d'allure attendue en chaleur, en % (approximation terrain
    dérivée des abaques de course sur route)."""
    if temp_c is None or temp_c <= 13:
        return 0.0
    excess = temp_c - 13
    humidity_factor = 1.0 + max(0.0, (humidity_pct - 50)) / 100.0
    return round(min(15.0, 0.55 * excess * humidity_factor), 2)


def wbgt_estimate(temp_c: float, humidity_pct: float, solar: bool = True) -> float | None:
    """Estimation simplifiée de l'indice WBGT (contrainte thermique)."""
    if temp_c is None or humidity_pct is None:
        return None
    tw = (temp_c * math.atan(0.151977 * (humidity_pct + 8.313659) ** 0.5)
          + math.atan(temp_c + humidity_pct) - math.atan(humidity_pct - 1.676331)
          + 0.00391838 * humidity_pct ** 1.5 * math.atan(0.023101 * humidity_pct)
          - 4.686035)
    wbgt = 0.7 * tw + 0.2 * (temp_c + (3 if solar else 0)) + 0.1 * temp_c
    return round(wbgt, 1)


def heat_risk(wbgt: float | None) -> str:
    if wbgt is None:
        return "inconnu"
    if wbgt < 18:
        return "faible"
    if wbgt < 23:
        return "modéré"
    if wbgt < 28:
        return "élevé"
    return "extrême — séance intense déconseillée"


def acclimatization_days(delta_temp_c: float) -> int:
    """Durée indicative d'acclimatation à la chaleur (10 à 14 j pour +10 °C)."""
    if not delta_temp_c or delta_temp_c <= 0:
        return 0
    return int(min(21, max(5, round(delta_temp_c * 1.2))))
