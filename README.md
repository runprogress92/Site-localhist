# Athlytics

Plateforme locale de suivi d'athlètes, connectée aux montres **Garmin**,
**Polar** et **COROS**.

Tout tourne sur votre machine : un serveur Python, une base SQLite, une
interface web. Aucune donnée ne part vers un service tiers, aucun compte à
créer, et **aucune dépendance à installer** — la bibliothèque standard de
Python suffit.

**Le plus simple — double-cliquez sur le fichier de lancement :**

| Windows | macOS et Linux |
|---|---|
| `LANCER-LE-SITE.bat` | `LANCER-LE-SITE.command` |

Il vérifie que Python est présent, vous dit quoi faire s'il manque, et
démarre le site. Aucune ligne de commande à taper.

**Ou en ligne de commande :**

```bash
python3 run.py
```

Dans les deux cas, l'application s'ouvre sur `http://127.0.0.1:8420`. Au
premier lancement, elle propose de générer un jeu de démonstration
(8 athlètes, 13 mois d'historique) pour que tout soit immédiatement visible.

---

## Sommaire

- [Ce que fait l'application](#ce-que-fait-lapplication)
- [Installation](#installation)
- [Récupérer les données de vos montres](#récupérer-les-données-de-vos-montres)
- [Les indicateurs, et ce qu'ils veulent dire](#les-indicateurs-et-ce-quils-veulent-dire)
- [Architecture](#architecture)
- [Tests](#tests)
- [Références](#références)

---

## Ce que fait l'application

### Vue d'ensemble du groupe
Condition, fatigue, forme et disponibilité de chaque athlète sur un écran,
avec les alertes qui demandent une décision aujourd'hui. Chaque alerte
affiche son seuil et la valeur observée : elle attire l'œil, elle ne décide
pas à votre place.

### Fiche athlète — sept onglets
| Onglet | Contenu |
|---|---|
| **Synthèse** | Graphique de forme, disponibilité du jour, répartition en zones, échéances |
| **Charge & forme** | PMC complet avec projection, ratio charge aiguë/chronique, monotonie, courbe record, distribution d'intensité |
| **Séances** | Journal filtrable, export CSV |
| **Bien-être & VFC** | Ligne de base 7 jours de ln(RMSSD), plage normale, décomposition du score de disponibilité, corrélation charge/VFC |
| **Physiologie** | Zones FC, puissance et allure, tests de laboratoire, courbe lactate avec seuils, prédictions de performance |
| **Planification** | Séances prévues, blocs, objectifs, simulation d'affûtage, taux de réalisation |
| **Notes & santé** | Notes d'entraînement, historique des blessures |

### Analyse d'une séance
Pistes synchronisées (fréquence cardiaque, puissance, réserve W′, allure,
altitude, mécanique de foulée) partageant un curseur commun, temps par zone,
tours, meilleurs efforts, trace GPS colorée par intensité, et une lecture en
français de ce que la séance signifie.

### Le reste
Calendrier mensuel fusionnant réalisé, planifié, bien-être et objectifs ·
relevés quotidiens du groupe · comparaison multi-athlètes sur toute
métrique · matrice de charge du groupe · connexions aux montres · réglages
des seuils et des pondérations.

---

## Installation

**Prérequis :** Python 3.10 ou plus récent. C'est tout.

*Sur Windows*, le plus simple est de l'installer depuis le Microsoft Store
(cherchez « Python 3.12 ») : les chemins sont configurés automatiquement.
Sur macOS et Linux, il est le plus souvent déjà présent.

```bash
git clone <votre-dépôt> athlytics
cd athlytics
python3 run.py
```

Sans git, téléchargez le ZIP depuis GitHub (bouton **Code → Download ZIP**),
extrayez-le, puis double-cliquez sur `LANCER-LE-SITE.bat` (Windows) ou
`LANCER-LE-SITE.command` (macOS, Linux).

### Options

```bash
python3 run.py --port 9000        # autre port
python3 run.py --no-browser       # ne pas ouvrir le navigateur
python3 run.py --seed             # (re)générer le jeu de démonstration
python3 run.py --seed-athletes 10 --seed-days 500
python3 run.py --reset            # repartir d'une base vide
python3 run.py --check            # vérifier l'installation
python3 run.py --verbose          # journaliser les requêtes
```

`--check` exécute une batterie de contrôles et affiche un rapport :

```
   [OK   ] Version de Python                     3.11.15
   [OK   ] Schéma de base de données             27 tables
   [OK   ] Codec FIT (aller-retour)              120 points
   [OK   ] TSS : 1 h à la FTP = 100              100.0
   [OK   ] hrTSS : 1 h au seuil = 100            100.0
   [OK   ] NP d'un effort constant = moyenne     250 W
   [OK   ] GAP : coût sur le plat = 3,6 J/kg/m   Minetti 2002
   [OK   ] VDOT : 5 km en 20 min ≈ 49            49.8
   [OK   ] Routes de l'API                       89 routes
   [OK   ] Interface web                         index.html
```

### Où sont mes données ?

Dans `data/athlytics.db` — un unique fichier SQLite. Sauvegardez-le, il
contient tout. La page **Réglages** propose un bouton de sauvegarde
(`VACUUM INTO`, donc une copie cohérente même serveur allumé).

### Configuration

Optionnelle. Créez `config.json` à la racine :

```json
{
  "host": "127.0.0.1",
  "port": 8420,
  "coach_name": "Votre nom",
  "providers": {
    "polar": { "client_id": "…", "client_secret": "…" }
  }
}
```

Les variables d'environnement `ATHLYTICS_PORT`, `ATHLYTICS_HOST`,
`ATHLYTICS_GARMIN_CLIENT_ID`… ont la priorité. Les clés d'API peuvent aussi
être saisies directement dans l'interface (page **Montres**).

---

## Récupérer les données de vos montres

### Option 1 — Import de fichiers (fonctionne tout de suite)

Les trois marques exportent des fichiers que l'application lit nativement :

| Marque | Chemin d'export | Format |
|---|---|---|
| **Garmin** | Garmin Connect → activité → ⋯ → « Exporter le fichier d'origine » | `.fit` |
| **Polar** | Polar Flow → séance → « Exporter la session » | `.tcx`, `.gpx` |
| **COROS** | Application COROS ou coros.com → activité → « Exporter » | `.fit`, `.tcx`, `.gpx` |

Glissez-déposez les fichiers dans l'application. Le décodeur FIT est écrit
de zéro dans ce projet : il lit l'en-tête, les messages de définition, les
horodatages compressés, les échelles et décalages, et les coordonnées en
semicercles. Vous obtenez exactement les mêmes données qu'avec une
connexion directe.

### Option 2 — Synchronisation directe

Elle demande un compte développeur auprès de chaque marque :

| Marque | Inscription | Authentification | Délai |
|---|---|---|---|
| **Garmin** | [Connect Developer Program](https://developer.garmin.com/gc-developer-program/health-api/) | OAuth 1.0a (HMAC-SHA1) | accès partenaire sur dossier |
| **Polar** | [admin.polaraccesslink.com](https://admin.polaraccesslink.com) | OAuth 2.0 | immédiat |
| **COROS** | [open.coros.com](https://open.coros.com) | OAuth 2.0 | quelques jours |

La page **Montres** affiche, pour chaque marque, les étapes d'inscription et
les URL exactes à déclarer dans la console du fabricant (redirection OAuth
et notifications push). Une fois les identifiants renseignés, chaque athlète
autorise l'accès depuis sa fiche.

Trois particularités que l'application gère pour vous :

- **Garmin** fonctionne en *push* : les séances sont poussées vers l'URL de
  notification dès qu'elles sont disponibles. Le mode *pull* sert au
  rattrapage d'historique, par fenêtres de 24 heures (contrainte de l'API).
- **Polar** impose un modèle *transactionnel* : on ouvre une transaction, on
  lit, puis on la valide. L'application ne valide **qu'après** import
  réussi — une interruption ne fait donc jamais perdre de séance.
- **COROS** fournit le fichier FIT complet : toutes les métriques sont
  recalculées localement avec **vos** seuils, pas ceux de la montre.

---

## Les indicateurs, et ce qu'ils veulent dire

### Charge d'entraînement

Toutes les échelles de charge sont ancrées sur la même convention : **une
heure exactement au seuil vaut 100 points**, quel que soit l'athlète et quel
que soit le capteur. C'est ce qui rend les séances comparables entre elles,
entre sports et entre athlètes.

| Mesure disponible | Modèle utilisé |
|---|---|
| Puissance | **TSS** — Coggan, à partir de la puissance normalisée |
| Allure (course) | **rTSS** — allure normalisée ajustée à la pente |
| Vitesse (natation) | **sTSS** — exposant 3, traînée hydrodynamique |
| Fréquence cardiaque | **hrTSS** — TRIMP de Banister rapporté à une heure au seuil |
| Rien | **sRPE** — Foster : RPE × durée, converti à l'échelle TSS |

### Condition, fatigue, forme

Modèle à impulsions-réponses de Banister, popularisé sous le nom de PMC :

- **CTL** (condition) — moyenne exponentielle de la charge sur 42 jours.
  Ce que vous avez construit.
- **ATL** (fatigue) — la même sur 7 jours. Ce que vous portez.
- **TSB** (forme) — `CTL(j−1) − ATL(j−1)`. Ce dont vous disposez aujourd'hui.

| TSB | État | Lecture |
|---|---|---|
| > +25 | affûté | Fenêtre de performance ; la condition se perd au-delà de trois semaines |
| +5 à +25 | frais | Bon compromis fraîcheur / condition |
| −10 à +5 | neutre | Charge et récupération à l'équilibre |
| −30 à −10 | productif | Zone de construction, fatigue assumée |
| < −30 | surcharge | À ne tenir que quelques jours |

### Signaux de risque

| Indicateur | Seuil | Ce qu'il détecte |
|---|---|---|
| **Ratio charge aiguë:chronique** | 0,80 – 1,30 | Au-delà de 1,50, l'incidence des blessures de surcharge augmente nettement sur 7 à 14 jours |
| **Monotonie** (Foster) | < 2,0 | Des charges quotidiennes trop uniformes limitent la surcompensation |
| **Contrainte** (strain) | < 6 000 | Charge hebdomadaire × monotonie ; les pics sont associés aux épisodes de maladie |
| **Rampe de CTL** | 3 à 7 pts/semaine | Vitesse de progression soutenable |

Le ratio est calculé des deux façons : moyennes glissantes 7 j / 28 j
(Gabbett) et moyennes exponentielles (Williams et al.), cette seconde forme
réagissant plus vite aux pics récents.

### Variabilité cardiaque

Le suivi porte sur la **moyenne glissante 7 jours de ln(RMSSD)**, jamais sur
la valeur d'un jour isolé, trop bruitée pour décider quoi que ce soit. Cette
moyenne est comparée à une plage normale personnelle (moyenne 60 jours
± 0,5 écart-type). Le coefficient de variation est également suivi : sa
hausse précède souvent la baisse de la moyenne.

### Disponibilité

Score de 0 à 100, moyenne pondérée de cinq composantes, chacune ramenée sur
100 où **50 correspond à la référence personnelle de l'athlète** :

| Composante | Poids par défaut |
|---|---|
| Variabilité cardiaque | 30 % |
| FC de repos | 15 % |
| Sommeil (durée + qualité) | 20 % |
| Ressenti déclaré (Hooper-Mackinnon) | 20 % |
| Bilan de charge (TSB, ratio A:C) | 15 % |

Les composantes absentes sont ignorées et les poids renormalisés : un simple
questionnaire suffit à produire un score. L'interface affiche toujours la
contribution de chaque composante — vous voyez *ce qui* fait monter ou
descendre le chiffre, jamais un score opaque. Les pondérations sont
modifiables dans **Réglages**.

### Puissance et allure

- **Puissance normalisée**, **facteur d'intensité**, **indice de
  variabilité**
- **Courbe record** (meilleure moyenne par durée) sur 42 jours, 90 jours,
  1 an et l'historique complet
- **Puissance critique et W′** ajustées sur les efforts de 2 à 20 minutes,
  domaine de validité du modèle hyperbolique
- **W′bal** — le solde de la réserve anaérobie seconde par seconde, forme
  différentielle de Skiba
- **Découplage** (Pw:HR ou Pa:HR) — sous 5 %, la base aérobie tient pour
  cette durée et cette intensité
- **GAP** — allure ajustée à la pente par le coût énergétique de Minetti
- **VDOT**, allures d'entraînement de Daniels, prédictions de Riegel

---

## Architecture

```
run.py                    lanceur, vérification d'installation
backend/
  schema.sql              27 tables
  db.py                   accès SQLite, flux compressés zlib
  server.py               serveur HTTP, routeur à motifs, gzip, multipart
  settings.py             configuration à trois niveaux
  profiles.py             résolution du profil physiologique à une date
  science/                zones, load, power, running, pmc, hrv,
                          readiness, physiology, risk
  ingest/                 fit (décodeur), fit_writer (encodeur),
                          xmlformats (TCX/GPX), pipeline
  providers/              oauth, base, garmin, polar, coros, registry
  api/                    89 routes
  seed/                   générateur de données de démonstration
frontend/
  index.html
  css/                    tokens, base, layout, components, charts, views
  js/lib/                 dom, format, api, router, store, ui
  js/charts/              core, plots, streams
  js/views/               11 vues
tests/                    107 tests
```

### Choix techniques

**Zéro dépendance.** Un outil qu'on installe une fois et qu'on veut retrouver
en état trois ans plus tard n'a pas besoin d'un arbre de dépendances qui
casse. Le serveur HTTP, le décodeur binaire FIT, la signature OAuth
HMAC-SHA1 et les graphiques SVG sont écrits ici. Le corollaire est que tout
fonctionne hors ligne, y compris les graphiques : aucun appel à un CDN.

**Le profil physiologique est historisé.** Analyser une séance de mars avec
la FTP de novembre fausserait sa charge. Chaque séance est analysée avec les
seuils qui étaient ceux de l'athlète *à sa date*. Mettre à jour un profil
propose de réanalyser les séances postérieures — pas les antérieures.

**Les jours de repos comptent.** Les moyennes exponentielles du PMC sont
calculées sur un calendrier complet, jours sans séance inclus. Les sauter
fausserait les constantes de temps.

**Les flux sont conservés.** Chaque séance détaillée garde ses séries à 1 Hz,
compressées en zlib (facteur ≈ 8). Une séance peut donc être entièrement
réanalysée sans le fichier d'origine.

---

## Tests

```bash
python3 tests/run_all.py            # 107 tests
python3 tests/run_all.py science    # un module
python3 run.py --check              # vérification rapide
```

Les tests ne vérifient pas que le code fait ce qu'il fait : ils vérifient des
**ancrages** (une heure au seuil vaut 100 points) et des **invariants** (la
puissance normalisée d'un effort constant égale sa moyenne ; la courbe
record est décroissante ; le modèle de puissance critique retrouve les
paramètres qui ont servi à générer ses points ; le VDOT reproduit les tables
publiées de Daniels ; le fichier FIT encodé se relit à l'identique).

---

## Références

- Banister E. W. (1975, 1991) — modèle à impulsions-réponses, TRIMP
- Coggan A. & Allen H. — *Training and Racing with a Power Meter* : NP, IF, TSS
- Friel J. — *The Triathlete's Training Bible* : zones sur la FC au seuil
- Foster C. (1998) — monotonie et contrainte de l'entraînement
- Gabbett T. (2016) — ratio charge aiguë:chronique
- Williams S. et al. (2017) — ratio A:C en moyennes exponentielles
- Skiba P. et al. (2012, 2015) — W′bal, forme différentielle
- Morton R. H. (1996) — modèle de puissance critique à 3 paramètres
- Minetti A. et al. (2002) — coût énergétique de la course en pente
- Daniels J. — *Daniels' Running Formula* : VDOT et allures
- Riegel P. (1981) — extrapolation de performance
- Plews D., Laursen P., Buchheit M. — suivi longitudinal de la VFC
- Seiler S. (2010), Treff G. et al. (2019) — modèle 3 zones, indice de polarisation
- Bosquet L. et al. (2007) — méta-analyse sur l'affûtage
- Hooper S. & Mackinnon L. (1995) — questionnaire de bien-être
- Uth N. et al. (2004), Tanaka H. et al. (2001) — estimations de terrain
- Jeukendrup A. (2014) — apports glucidiques à l'effort

---

## Licence et données

Le code de ce projet vous appartient. Les données de vos athlètes ne
quittent jamais votre machine : il n'y a ni télémétrie, ni compte, ni appel
réseau — hormis, si vous les configurez, les appels aux API des fabricants
de montres, qui vont directement de votre machine à leurs serveurs.
