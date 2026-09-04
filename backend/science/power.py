"""Analyse de la puissance mécanique.

* **NP** (Normalized Power, Coggan) — moyenne glissante 30 s, élevée à la
  puissance 4, moyennée, racine 4ᵉ. Rend compte du coût métabolique
  disproportionné des variations d'intensité.
* **xPower** (Skiba) — variante à moyenne exponentielle 25 s.
* **Courbe record** (Mean Maximal Power) — meilleure puissance moyenne pour
  chaque durée, calculée en O(n) par sommes préfixes.
* **Puissance critique** — modèle hyperbolique à 2 paramètres
  P(t) = W'/t + CP, ajusté par régression linéaire sur (1/t, P).
* **W'bal** — solde de la réserve anaérobie au fil de la séance
  (forme différentielle de Skiba et al., 2012 ; τ de Skiba 2015).
* **Découplage aérobie** (Pw:HR) — dérive du rapport puissance/FC entre la
  première et la seconde moitié d'un effort en aérobie.
"""
from __future__ import annotations

import math
from typing import Sequence

# Durées standard de la courbe record (secondes)
MMP_DURATIONS = [
    1, 2, 3, 5, 8, 10, 12, 15, 20, 30, 45,
    60, 75, 90, 120, 150, 180, 240, 300, 360, 420, 480, 540, 600,
    720, 900, 1200, 1500, 1800, 2400, 3000, 3600, 4500, 5400, 7200,
    10800, 14400, 18000,
]


def _clean(series: Sequence[float | None]) -> list[float]:
    """Remplace les trous par 0 (arrêt = puissance nulle, physiquement juste)."""
    return [0.0 if v is None else float(v) for v in series]


def rolling_mean(series: Sequence[float], window: int) -> list[float]:
    """Moyenne glissante causale, O(n)."""
    if window <= 1:
        return list(series)
    out: list[float] = []
    acc = 0.0
    for i, v in enumerate(series):
        acc += v
        if i >= window:
            acc -= series[i - window]
        out.append(acc / min(i + 1, window))
    return out


def normalized_power(series: Sequence[float | None], sample_rate: float = 1.0) -> float | None:
    """Puissance normalisée. Nécessite au moins 30 s de données."""
    data = _clean(series)
    if len(data) < 30 * sample_rate:
        return None
    window = max(1, int(round(30 * sample_rate)))
    smoothed = rolling_mean(data, window)
    # Les 30 premières secondes sont incomplètes : on les écarte (convention Coggan)
    usable = smoothed[window - 1:] or smoothed
    fourth = sum(v ** 4 for v in usable) / len(usable)
    return round(fourth ** 0.25, 1)


def xpower(series: Sequence[float | None], sample_rate: float = 1.0) -> float | None:
    """xPower de Skiba : moyenne exponentielle de constante 25 s."""
    data = _clean(series)
    if len(data) < 25 * sample_rate:
        return None
    dt = 1.0 / sample_rate
    tau = 25.0
    alpha = 1 - math.exp(-dt / tau)
    ewma = data[0]
    acc = 0.0
    for v in data:
        ewma += alpha * (v - ewma)
        acc += ewma ** 4
    return round((acc / len(data)) ** 0.25, 1)


def variability_index(np_w: float | None, avg_w: float | None) -> float | None:
    """VI = NP / Pmoy. > 1,05 ⇒ effort haché (course en peloton, relances)."""
    if not np_w or not avg_w or avg_w <= 0:
        return None
    return round(np_w / avg_w, 3)


def work_kj(series: Sequence[float | None], sample_rate: float = 1.0) -> float | None:
    """Travail mécanique total en kilojoules."""
    data = _clean(series)
    if not data:
        return None
    dt = 1.0 / sample_rate
    return round(sum(data) * dt / 1000.0, 1)


def efficiency_factor(np_or_speed: float | None, avg_hr: float | None) -> float | None:
    """Facteur d'efficacité : NP/FC (vélo) ou vitesse/FC (course).
    Sa hausse à FC constante traduit une amélioration de l'endurance aérobie."""
    if not np_or_speed or not avg_hr or avg_hr <= 0:
        return None
    return round(np_or_speed / avg_hr, 4)


def aerobic_decoupling(power_or_speed: Sequence[float | None],
                       hr: Sequence[float | None],
                       sample_rate: float = 1.0) -> float | None:
    """Découplage Pw:HR ou Pa:HR, en %.

    On compare le rapport intensité/FC de la première et de la seconde moitié.
    Interprétation usuelle (Friel) : < 5 % ⇒ base aérobie solide pour la durée
    et l'intensité considérées ; > 5 % ⇒ dérive cardiaque.
    Non pertinent en dessous de ~45 min ou sur un effort non stabilisé.
    """
    n = min(len(power_or_speed), len(hr))
    if n < 45 * 60 * sample_rate * 0.5:      # < ~22 min : trop court
        return None
    half = n // 2

    def ratio(a, b):
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y and y > 0]
        if len(pairs) < 60:
            return None
        mean_p = sum(p for p, _ in pairs) / len(pairs)
        mean_h = sum(h for _, h in pairs) / len(pairs)
        return mean_p / mean_h if mean_h else None

    r1 = ratio(power_or_speed[:half], hr[:half])
    r2 = ratio(power_or_speed[half:n], hr[half:n])
    if not r1 or not r2:
        return None
    return round(100.0 * (r1 - r2) / r1, 2)


# ------------------------------------------------------------- courbe record
def mean_maximal(series: Sequence[float | None], durations: Sequence[int] = MMP_DURATIONS,
                 sample_rate: float = 1.0) -> dict[int, tuple[float, int]]:
    """Meilleure moyenne pour chaque durée.

    Renvoie {durée_s: (valeur, offset_de_départ_s)}. Complexité O(n·|durées|)
    grâce aux sommes préfixes.
    """
    data = _clean(series)
    n = len(data)
    if n == 0:
        return {}
    prefix = [0.0] * (n + 1)
    total = 0.0
    for i, v in enumerate(data):
        total += v
        prefix[i + 1] = total
    out: dict[int, tuple[float, int]] = {}
    for d in durations:
        w = int(round(d * sample_rate))
        if w < 1 or w > n:
            continue
        # Les sommes de toutes les fenêtres sont obtenues d'un coup par zip
        # sur les sommes préfixes, puis max() et index() travaillent au niveau
        # C. Une boucle Python explicite est cinq fois plus lente ici, et cette
        # fonction s'exécute à chaque import de séance.
        sums = list(map(float.__sub__, prefix[w:], prefix[:n - w + 1]))
        best = max(sums)
        if best > 0:
            best_i = sums.index(best)
            out[d] = (round(best / w, 1), int(best_i / sample_rate))
    return out


def critical_power(efforts: Sequence[tuple[float, float]]) -> dict | None:
    """Ajuste le modèle à 2 paramètres P = W'/t + CP.

    ``efforts`` : liste de (durée_s, puissance_moyenne_W). On ne retient que
    les efforts de 2 à 20 min, domaine de validité du modèle hyperbolique
    (au-delà, CP est surestimée ; en deçà, la composante anaérobie domine).
    Régression des moindres carrés de P sur x = 1/t.
    """
    pts = [(t, p) for t, p in efforts if 120 <= t <= 1200 and p and p > 0]
    if len(pts) < 2:
        return None
    xs = [1.0 / t for t, _ in pts]
    ys = [p for _, p in pts]
    n = len(pts)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    w_prime = sxy / sxx          # pente = W' (joules)
    cp = my - w_prime * mx       # ordonnée à l'origine = CP (watts)
    # coefficient de détermination
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (cp + w_prime * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    if cp <= 0 or w_prime <= 0:
        return None
    return {
        "cp_w": round(cp, 1),
        "w_prime_j": round(w_prime, 0),
        "r2": round(r2, 4) if r2 is not None else None,
        "n_points": n,
        "ftp_estimate_w": round(cp * 0.97, 1),   # FTP ≈ 97 % de CP en pratique
    }


def w_bal(series: Sequence[float | None], cp: float, w_prime: float,
          sample_rate: float = 1.0) -> list[float]:
    """W'bal — forme différentielle (Skiba 2012, τ de Skiba 2015).

    Au-dessus de CP, W' se vide au débit (P − CP) ; en dessous, il se
    reconstitue exponentiellement avec une constante de temps τ fonction du
    déficit de puissance :  τ = 546·e^(−0,01·DCP) + 316.
    """
    data = _clean(series)
    if not data or not cp or not w_prime:
        return []
    dt = 1.0 / sample_rate
    below = [cp - p for p in data if p < cp]
    dcp = sum(below) / len(below) if below else 0.0
    tau = 546.0 * math.exp(-0.01 * dcp) + 316.0
    bal = w_prime
    out = []
    for p in data:
        if p > cp:
            bal -= (p - cp) * dt
        else:
            bal += (w_prime - bal) * (1 - math.exp(-dt / tau))
        bal = max(0.0, min(w_prime, bal))
        out.append(round(bal, 1))
    return out


# ------------------------------------------------------- profil de puissance
# Repères de Coggan (W/kg) — bornes basses des catégories, hommes.
POWER_PROFILE_M = {
    5:    [(24.04, "Classe mondiale"), (20.27, "Excellent"), (16.84, "Très bon"),
           (13.75, "Bon"), (10.66, "Moyen"), (7.57, "Débutant")],
    60:   [(11.50, "Classe mondiale"), (9.64, "Excellent"), (7.96, "Très bon"),
           (6.44, "Bon"), (4.93, "Moyen"), (3.41, "Débutant")],
    300:  [(7.60, "Classe mondiale"), (6.36, "Excellent"), (5.25, "Très bon"),
           (4.24, "Bon"), (3.23, "Moyen"), (2.22, "Débutant")],
    1200: [(6.40, "Classe mondiale"), (5.36, "Excellent"), (4.42, "Très bon"),
           (3.56, "Bon"), (2.71, "Moyen"), (1.86, "Débutant")],
}
POWER_PROFILE_F = {
    5:    [(19.42, "Classe mondiale"), (16.38, "Excellent"), (13.63, "Très bon"),
           (11.13, "Bon"), (8.63, "Moyen"), (6.13, "Débutant")],
    60:   [(9.29, "Classe mondiale"), (7.79, "Excellent"), (6.43, "Très bon"),
           (5.20, "Bon"), (3.98, "Moyen"), (2.75, "Débutant")],
    300:  [(6.61, "Classe mondiale"), (5.53, "Excellent"), (4.56, "Très bon"),
           (3.68, "Bon"), (2.80, "Moyen"), (1.92, "Débutant")],
    1200: [(5.69, "Classe mondiale"), (4.76, "Excellent"), (3.93, "Très bon"),
           (3.16, "Bon"), (2.40, "Moyen"), (1.63, "Débutant")],
}


def power_profile(w_per_kg: float, duration_s: int, sex: str = "M") -> str | None:
    """Situe une puissance relative dans la table de référence de Coggan."""
    table = POWER_PROFILE_F if sex == "F" else POWER_PROFILE_M
    ref = table.get(duration_s)
    if not ref or w_per_kg is None:
        return None
    for threshold, label in ref:
        if w_per_kg >= threshold:
            return label
    return "Non entraîné"


def phenotype(mmp: dict[int, float], weight_kg: float, sex: str = "M") -> str | None:
    """Phénotype de puissance : sprinteur / pistard / rouleur / grimpeur.

    Comparaison des rangs relatifs sur 5 s (neuromusculaire), 1 min
    (anaérobie), 5 min (VO2max) et 20 min (seuil).
    """
    if not weight_kg or weight_kg <= 0:
        return None
    scores = {}
    for d in (5, 60, 300, 1200):
        v = mmp.get(d)
        if v is None:
            return None
        label = power_profile(v / weight_kg, d, sex)
        order = ["Non entraîné", "Débutant", "Moyen", "Bon", "Très bon",
                 "Excellent", "Classe mondiale"]
        scores[d] = order.index(label) if label in order else 0
    sprint = scores[5]
    anaerobic = scores[60]
    vo2 = scores[300]
    threshold = scores[1200]
    if sprint >= max(anaerobic, vo2, threshold) + 1:
        return "Sprinteur"
    if anaerobic >= max(vo2, threshold) + 1:
        return "Pistard / puncheur"
    if threshold >= max(sprint, anaerobic) + 1:
        return "Rouleur / contre-la-montre"
    if vo2 >= max(sprint, anaerobic, threshold):
        return "Grimpeur / puncheur"
    return "Profil équilibré (tout-terrain)"


# ------------------------------------------- modèle puissance-durée complet
def power_duration(t: float, cp: float, w_prime: float,
                   p_max: float | None = None) -> float:
    """Modèle à 3 paramètres de Morton (1996) :

        P(t) = CP + W' / (t + W'/(Pmax − CP))

    Le modèle hyperbolique à 2 paramètres diverge quand t tend vers zéro
    (il prédirait plusieurs milliers de watts sur 5 s). Le terme correctif de
    Morton borne la courbe par la puissance maximale instantanée : P(0) = Pmax
    et P(∞) = CP. C'est le modèle à utiliser dès qu'on descend sous 2 minutes.
    """
    if t <= 0 or not cp or not w_prime:
        return 0.0
    if not p_max or p_max <= cp:
        return cp + w_prime / t
    k = w_prime / (p_max - cp)
    return cp + w_prime / (t + k)


def speed_duration(t: float, cs: float, d_prime: float,
                   v_max: float | None = None) -> float:
    """Équivalent en course : modèle vitesse-durée borné par la vitesse maximale."""
    if t <= 0 or not cs:
        return 0.0
    if not v_max or v_max <= cs:
        return cs + (d_prime or 0) / t
    k = (d_prime or 0) / (v_max - cs)
    return cs + (d_prime or 0) / (t + k)


def modeled_curve(durations, cp: float, w_prime: float,
                  p_max: float | None = None) -> dict[int, float]:
    """Courbe puissance-durée théorique, pour comparaison avec la courbe réelle."""
    return {int(d): round(power_duration(d, cp, w_prime, p_max), 1) for d in durations}
