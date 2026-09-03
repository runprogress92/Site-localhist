"""Archétypes d'athlètes pour le jeu de démonstration.

Chaque profil est cohérent : les seuils, le volume hebdomadaire, la
répartition des sports et la trajectoire de progression correspondent à ce
que l'on observe réellement pour le niveau annoncé.
"""
from __future__ import annotations

ARCHETYPES = [
    {
        "first_name": "Camille", "last_name": "Reynaud", "sex": "F",
        "birth_date": "1996-04-18", "height_cm": 168, "weight_kg": 54.5,
        "primary_sport": "running", "discipline": "10 km / semi-marathon",
        "level": "national", "country": "France", "accent": "#4f8ff7",
        "physio": {"hr_max": 196, "hr_rest": 42, "hr_lt1": 158, "hr_lt2": 178,
                   "vo2max": 62.5, "vvo2max": 5.28, "threshold_pace_s_km": 210,
                   "vdot": 60.0, "running_economy": 197},
        "weekly_hours": 8.5, "sessions_per_week": 9,
        "sports": {"running": 0.85, "cycling": 0.08, "strength_training": 0.07},
        "progression": 0.05,
        "events": [("Semi-marathon de Paris", 92, "A", 21097.5, 4620),
                   ("10 km de Lyon", 34, "B", 10000, 2085),
                   ("Championnats de France 10 000 m", 175, "A", 10000, 2040)],
    },
    {
        "first_name": "Thomas", "last_name": "Bellanger", "sex": "M",
        "birth_date": "1991-09-02", "height_cm": 181, "weight_kg": 71.0,
        "primary_sport": "cycling", "discipline": "Route / contre-la-montre",
        "level": "élite", "country": "France", "accent": "#e08d3c",
        "physio": {"hr_max": 189, "hr_rest": 40, "hr_lt1": 148, "hr_lt2": 171,
                   "vo2max": 71.0, "ftp_w": 340, "cp_w": 352, "w_prime_j": 21500,
                   "pmax_w": 1280},
        "weekly_hours": 16.0, "sessions_per_week": 8,
        "sports": {"cycling": 0.92, "running": 0.04, "strength_training": 0.04},
        "progression": 0.04,
        "events": [("Chrono des Nations", 120, "A", 25000, 1980),
                   ("Tour du Jura", 60, "B", 160000, 15000)],
    },
    {
        "first_name": "Inès", "last_name": "Marchetti", "sex": "F",
        "birth_date": "1999-01-27", "height_cm": 172, "weight_kg": 59.0,
        "primary_sport": "cycling", "discipline": "Triathlon longue distance",
        "level": "compétiteur", "country": "France", "accent": "#3fb98c",
        "physio": {"hr_max": 192, "hr_rest": 46, "hr_lt1": 152, "hr_lt2": 174,
                   "vo2max": 58.0, "ftp_w": 232, "cp_w": 240, "w_prime_j": 14200,
                   "threshold_pace_s_km": 258, "vdot": 50.5},
        "weekly_hours": 13.0, "sessions_per_week": 10,
        "sports": {"cycling": 0.45, "running": 0.32, "swimming": 0.18,
                   "strength_training": 0.05},
        "progression": 0.06,
        "events": [("Ironman 70.3 Aix", 105, "A", 113000, 18900),
                   ("Triathlon de Gérardmer", 48, "B", 51500, 9600)],
    },
    {
        "first_name": "Youssef", "last_name": "Amrani", "sex": "M",
        "birth_date": "1994-06-11", "height_cm": 176, "weight_kg": 63.5,
        "primary_sport": "trail_running", "discipline": "Trail long / ultra",
        "level": "national", "country": "France", "accent": "#b1418b",
        "physio": {"hr_max": 191, "hr_rest": 41, "hr_lt1": 150, "hr_lt2": 172,
                   "vo2max": 68.0, "vvo2max": 5.55, "threshold_pace_s_km": 216,
                   "vdot": 58.0},
        "weekly_hours": 11.0, "sessions_per_week": 8,
        "sports": {"trail_running": 0.62, "running": 0.24, "cycling": 0.08,
                   "strength_training": 0.06},
        "progression": 0.04,
        "events": [("Trail des Aiguilles Rouges", 78, "A", 54000, 25200),
                   ("Ultra du Vercors", 160, "A", 85000, 43200)],
    },
    {
        "first_name": "Léa", "last_name": "Fontaine", "sex": "F",
        "birth_date": "2003-11-05", "height_cm": 165, "weight_kg": 51.0,
        "primary_sport": "running", "discipline": "800 m / 1 500 m",
        "level": "national", "country": "France", "accent": "#d8543f",
        "physio": {"hr_max": 201, "hr_rest": 48, "hr_lt1": 162, "hr_lt2": 183,
                   "vo2max": 64.0, "vvo2max": 5.60, "threshold_pace_s_km": 202,
                   "vdot": 62.5},
        "weekly_hours": 7.0, "sessions_per_week": 8,
        "sports": {"running": 0.80, "strength_training": 0.14, "cycling": 0.06},
        "progression": 0.07,
        "events": [("Meeting de Montreuil 1 500 m", 66, "A", 1500, 250),
                   ("Championnats de France Espoirs", 130, "A", 800, 128)],
    },
    {
        "first_name": "Marc", "last_name": "Delaunay", "sex": "M",
        "birth_date": "1985-03-22", "height_cm": 184, "weight_kg": 79.5,
        "primary_sport": "cycling", "discipline": "Cyclosport / gran fondo",
        "level": "compétiteur", "country": "France", "accent": "#7b56c9",
        "physio": {"hr_max": 181, "hr_rest": 52, "hr_lt1": 141, "hr_lt2": 162,
                   "vo2max": 54.0, "ftp_w": 276, "cp_w": 284, "w_prime_j": 19800,
                   "pmax_w": 1080},
        "weekly_hours": 9.5, "sessions_per_week": 6,
        "sports": {"cycling": 0.80, "running": 0.10, "strength_training": 0.10},
        "progression": 0.03,
        "events": [("La Marmotte", 112, "A", 174000, 25200),
                   ("Étape du Tour", 145, "B", 145000, 21600)],
    },
    {
        "first_name": "Sofia", "last_name": "Ferreira", "sex": "F",
        "birth_date": "1997-08-14", "height_cm": 170, "weight_kg": 57.5,
        "primary_sport": "swimming", "discipline": "Eau libre / 1 500 m",
        "level": "national", "country": "Portugal", "accent": "#5b8fd6",
        "physio": {"hr_max": 190, "hr_rest": 47, "hr_lt1": 150, "hr_lt2": 172,
                   "vo2max": 56.0, "critical_speed_ms": 1.32},
        "weekly_hours": 12.0, "sessions_per_week": 9,
        "sports": {"swimming": 0.72, "running": 0.13, "strength_training": 0.15},
        "progression": 0.04,
        "events": [("Traversée du lac d'Annecy", 88, "A", 5000, 3900),
                   ("Championnats nationaux 1 500 m NL", 140, "A", 1500, 1010)],
    },
    {
        "first_name": "Julien", "last_name": "Novak", "sex": "M",
        "birth_date": "2000-02-09", "height_cm": 179, "weight_kg": 68.0,
        "primary_sport": "running", "discipline": "Marathon",
        "level": "compétiteur", "country": "France", "accent": "#c9c04a",
        "physio": {"hr_max": 194, "hr_rest": 44, "hr_lt1": 154, "hr_lt2": 176,
                   "vo2max": 63.5, "vvo2max": 5.35, "threshold_pace_s_km": 214,
                   "vdot": 57.5},
        "weekly_hours": 9.0, "sessions_per_week": 7,
        "sports": {"running": 0.88, "cycling": 0.06, "strength_training": 0.06},
        "progression": 0.05,
        "events": [("Marathon de Berlin", 118, "A", 42195, 9300),
                   ("Semi de Boulogne", 55, "B", 21097.5, 4350)],
    },
    {
        "first_name": "Anaïs", "last_name": "Perrot", "sex": "F",
        "birth_date": "1993-12-01", "height_cm": 174, "weight_kg": 63.0,
        "primary_sport": "cycling", "discipline": "VTT cross-country",
        "level": "élite", "country": "France", "accent": "#3fb98c",
        "physio": {"hr_max": 188, "hr_rest": 43, "hr_lt1": 147, "hr_lt2": 169,
                   "vo2max": 65.5, "ftp_w": 268, "cp_w": 276, "w_prime_j": 17400,
                   "pmax_w": 980},
        "weekly_hours": 14.0, "sessions_per_week": 9,
        "sports": {"cycling": 0.78, "running": 0.12, "strength_training": 0.10},
        "progression": 0.045,
        "events": [("Coupe de France VTT XCO", 40, "A", 30000, 5400),
                   ("Championnats de France XCO", 96, "A", 32000, 5700)],
    },
    {
        "first_name": "Hugo", "last_name": "Lacroix", "sex": "M",
        "birth_date": "1988-07-30", "height_cm": 187, "weight_kg": 82.0,
        "primary_sport": "rowing", "discipline": "Aviron / indoor",
        "level": "compétiteur", "country": "France", "accent": "#e08d3c",
        "physio": {"hr_max": 184, "hr_rest": 45, "hr_lt1": 144, "hr_lt2": 166,
                   "vo2max": 58.5, "ftp_w": 310, "cp_w": 318, "w_prime_j": 23000},
        "weekly_hours": 8.0, "sessions_per_week": 6,
        "sports": {"rowing": 0.62, "cycling": 0.18, "strength_training": 0.20},
        "progression": 0.035,
        "events": [("Championnats indoor 2 000 m", 72, "A", 2000, 380)],
    },
]

TEAMS = [
    {"name": "Groupe Élite Endurance", "sport": "multisport",
     "coach": "Entraîneur principal", "season": "2026", "color": "#4f8ff7"},
    {"name": "Pôle Route & Piste", "sport": "cycling",
     "coach": "Entraîneur cyclisme", "season": "2026", "color": "#e08d3c"},
]

INJURY_TEMPLATES = [
    {"body_part": "Tendon d'Achille", "type": "Tendinopathie", "mechanism": "surcharge",
     "severity": 3, "diagnosis": "Tendinopathie corporéale gauche, stade 2",
     "treatment": "Protocole excentrique Alfredson, réduction du volume en côte"},
    {"body_part": "Genou", "type": "Syndrome fémoro-patellaire", "mechanism": "surcharge",
     "severity": 2, "diagnosis": "Douleur antérieure à la montée d'escalier",
     "treatment": "Renforcement du moyen fessier, augmentation de la cadence"},
    {"body_part": "Ischio-jambiers", "type": "Élongation", "mechanism": "traumatique",
     "severity": 3, "diagnosis": "Lésion myo-aponévrotique grade I à droite",
     "treatment": "Repos 10 jours puis réathlétisation progressive"},
    {"body_part": "Bas du dos", "type": "Lombalgie", "mechanism": "surcharge",
     "severity": 2, "diagnosis": "Contracture para-vertébrale après bloc de charge",
     "treatment": "Gainage, révision de la position sur le vélo"},
]

NOTE_TEMPLATES = [
    ("technique", "Fréquence de foulée encore basse en fin de séance longue "
                  "(168 ppm contre 176 au départ) : signe de fatigue neuromusculaire, "
                  "à retravailler par des lignes droites en fin de footing."),
    ("mental", "Très bonne gestion de l'allure sur la séance au seuil : premier "
               "et dernier bloc à deux secondes près. La confiance revient."),
    ("nutrition", "Rapporte des sensations de fringale au-delà de deux heures. "
                  "Passer à 70 g de glucides par heure sur les sorties longues, "
                  "à tester à l'entraînement avant la course."),
    ("médical", "Contrôle sanguin : ferritine à 28 µg/L, en baisse. Supplémentation "
                "mise en place et contrôle prévu dans six semaines."),
    ("logistique", "Stage en altitude confirmé (Font-Romeu, 1 850 m). Prévoir un "
                   "allègement de la charge les trois premiers jours."),
    ("technique", "Puissance très irrégulière en montée (indice de variabilité 1,18) : "
                  "travailler le maintien de l'allure sur les portions longues."),
    ("mental", "Séance écourtée d'un commun accord : jambes lourdes annoncées et VFC "
               "sous la plage normale. Bonne décision, à valoriser."),
]
