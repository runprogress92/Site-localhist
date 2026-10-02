# Référence de l'API

Toutes les routes sont préfixées par `/api`, renvoient du JSON en UTF-8 et
acceptent du JSON en entrée. Le serveur écoute par défaut sur
`http://127.0.0.1:8420`.

**Conventions d'unités** — durées en secondes, distances en mètres, vitesses
en m/s, puissances en watts. Toute unité dérogeant à cette règle est
suffixée dans le nom du champ (`weight_kg`, `pace_s_km`, `height_cm`).

**Dates** — `YYYY-MM-DD` pour les dates civiles, ISO-8601 UTC pour les
instants (`2026-05-12T08:00:00Z`).

**Erreurs** — code HTTP standard et corps
`{"error": "…", "detail": …, "status": 400}`.

```bash
curl -s localhost:8420/api/health | python3 -m json.tool
```

---

## Athlètes

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/athletes` | Roster avec l'état du jour de chacun (CTL, ATL, TSB, disponibilité, alertes, volume hebdomadaire). `?archived=true` pour inclure les archivés. |
| `POST` | `/athletes` | Crée un athlète. Un profil physiologique par défaut est généré si aucun n'est fourni. |
| `GET` | `/athletes/{id}` | Fiche complète : profil courant, historique des profils, zones, totaux, appareils. |
| `PATCH` | `/athletes/{id}` | Modifie la fiche. |
| `DELETE` | `/athletes/{id}` | Archive l'athlète. `?hard=true` supprime définitivement. |
| `GET` | `/athletes/{id}/summary` | Charge utile du tableau de bord. `?days=120` |
| `POST` | `/athletes/{id}/physiology` | Ajoute une ligne de profil **datée**. `{"reanalyze": true}` recalcule les séances postérieures. |
| `GET` | `/athletes/{id}/zones` | Zones FC, puissance et allure. `?date=` pour une date passée. |
| `GET` | `/athletes/{id}/zones/{kind}` | `hr`, `power` ou `pace`. `?model=friel_lthr\|hrmax\|karvonen\|seiler3` |
| `GET` | `/athletes/{id}/power-curve` | Courbe record sur plusieurs fenêtres + modèle CP/W′ + phénotype. `?kind=power\|speed` |
| `GET` | `/athletes/{id}/records` | Meilleures performances par durée, avec la séance d'origine. |
| `GET` | `/athletes/{id}/progression` | Agrégats mensuels et historique de profil. `?months=18` |
| `GET` `POST` | `/athletes/{id}/notes` | Notes d'entraînement. |
| `GET` `POST` | `/athletes/{id}/injuries` | Blessures. |
| `PATCH` | `/injuries/{id}` | Met à jour une blessure ; repasse l'athlète en « actif » si plus rien n'est ouvert. |
| `POST` | `/alerts/{id}/acknowledge` | Acquitte une alerte. |

**Exemple — créer un athlète**

```bash
curl -X POST localhost:8420/api/athletes \
  -H 'Content-Type: application/json' \
  -d '{"first_name":"Camille","last_name":"Reynaud","sex":"F",
       "birth_date":"1996-04-18","primary_sport":"running",
       "physiology":{"hr_max":196,"hr_rest":42,"hr_lt2":178,
                     "threshold_pace_s_km":210,"vo2max":62.5}}'
```

---

## Activités

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/activities` | Liste filtrable. Filtres : `athlete_id`, `sport`, `from`, `to`, `search`, `provider`, `min_duration` (min). Pagination `limit`/`offset`, tri `sort`/`order`. |
| `GET` | `/activities/{id}` | Détail : tours, temps par zone, meilleurs efforts, contexte physiologique, comparaison aux 90 derniers jours. |
| `GET` | `/activities/{id}/streams` | Flux temporels. `?points=2000` fixe la résolution, `?kinds=power,heart_rate` restreint, `?derived=true` ajoute W′bal, moyenne glissante 30 s et allure ajustée. |
| `PATCH` | `/activities/{id}` | Nom, notes, étiquettes, RPE, ressenti, sport. |
| `DELETE` | `/activities/{id}` | Supprime la séance et ses flux. |
| `POST` | `/activities/{id}/reanalyze` | Recalcule depuis les flux stockés, avec les seuils en vigueur. |
| `POST` | `/activities/upload?athlete_id=N` | Import multipart de fichiers `.fit`, `.tcx`, `.gpx` (plusieurs à la fois). |
| `GET` | `/activities/{id}/export.csv` | Flux détaillés en CSV. |
| `GET` | `/activities/{id}/export.fit` | Réencodage FIT. |
| `GET` | `/activities/{id}/gpx` | Trace GPS avec extensions Garmin. |
| `GET` | `/activities/export.csv` | Export tabulaire de la liste (mêmes filtres). |

**Exemple — importer des fichiers**

```bash
curl -X POST "localhost:8420/api/activities/upload?athlete_id=1" \
  -F "file=@samples/garmin-velo-seuil.fit" \
  -F "file=@samples/coros-trail-longue.gpx"
```

---

## Charge et analyse

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/athletes/{id}/pmc` | Série CTL/ATL/TSB et ratios. `?days=180&project=21` projette les séances planifiées. |
| `GET` | `/athletes/{id}/load` | Charge agrégée. `?group=week\|month&periods=26`, ventilée par sport. |
| `GET` | `/athletes/{id}/calendar` | Calendrier fusionné : réalisé, planifié, bien-être, objectifs, blocs. `?from=&to=` |
| `GET` | `/athletes/{id}/zone-distribution` | Répartition par zone, distribution 3 zones, indice de polarisation et lecture en français. `?days=90&kind=hr` |
| `GET` | `/team/overview` | Vue d'ensemble du groupe. |
| `GET` | `/team/matrix` | Matrice charge × jour. `?days=42` |
| `GET` | `/compare` | Comparaison. `?athletes=1,2,3&metric=ctl&days=120` |
| `GET` | `/search` | Recherche transverse. `?q=` |

Métriques comparables : `ctl`, `atl`, `tsb`, `load`, `acwr_ewma`,
`monotony`, `strain`, `readiness`, `hrv_ln_rmssd`, `resting_hr`,
`sleep_total_min`.

---

## Bien-être et disponibilité

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/athletes/{id}/wellness` | Relevés sur une période, avec la ligne de base VFC. `?days=120` ou `?from=&to=` |
| `POST` | `/athletes/{id}/wellness` | Enregistre un relevé et recalcule la disponibilité. Fusionne avec l'existant du même jour. |
| `DELETE` | `/athletes/{id}/wellness/{date}` | Supprime un relevé. |
| `GET` | `/athletes/{id}/readiness` | Score du jour, décomposé par composante et par levier. |
| `GET` | `/athletes/{id}/hrv` | Analyse VFC complète : ln(RMSSD), lignes de base 7 j et 30 j, plage normale, coefficient de variation, écart de FC de repos. `?days=180` |
| `GET` | `/wellness/today` | Tableau des relevés du jour pour tout le groupe. `?date=` |

**Exemple — relevé du matin**

```bash
curl -X POST localhost:8420/api/athletes/1/wellness \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-09-04","hrv_rmssd":62,"resting_hr":46,
       "sleep_total_min":470,"fatigue":3,"soreness":2,"mood":2,
       "stress_subj":3,"sleep_quality":2,"motivation":2}'
```

Réponse : `{"date": "…", "readiness": {"score": 68.4, "flag": "ambre",
"components": {...}, "drivers": [...], "advice": "…"}}`

---

## Planification

| Méthode | Route | Description |
|---|---|---|
| `GET` `POST` | `/athletes/{id}/planned` | Séances prévues. `?from=&to=` |
| `PATCH` `DELETE` | `/planned/{id}` | Modifie ou supprime. |
| `POST` | `/athletes/{id}/planned/match` | Rapproche automatiquement plan et réalisé, calcule la conformité. |
| `POST` | `/athletes/{id}/planned/generate` | Génère une semaine polarisée. `{"weekly_load": 420, "start": "…", "replace": true}` |
| `GET` | `/athletes/{id}/compliance` | Taux de réalisation par semaine. `?weeks=12` |
| `GET` `POST` | `/athletes/{id}/blocks` | Blocs de préparation. |
| `GET` `POST` | `/athletes/{id}/events` | Objectifs. |
| `PATCH` `DELETE` | `/events/{id}` | Modifie ou supprime un objectif. |
| `GET` | `/athletes/{id}/taper` | Simulation d'affûtage. `?date=&tsb=15&taper_days=14`. Sans date, vise le prochain objectif A. |

---

## Tests et physiologie

| Méthode | Route | Description |
|---|---|---|
| `GET` `POST` | `/athletes/{id}/tests` | Tests de laboratoire et de terrain. Un test lactate accepte un tableau `points`. |
| `GET` | `/tests/{id}/analysis` | Détermination de LT1 et LT2 (méthodes « base + 0,4 mmol », OBLA 4 mmol, Dmax modifiée). |
| `DELETE` | `/tests/{id}` | Supprime un test. |
| `GET` | `/athletes/{id}/predictions` | Prédictions de Riegel + allures de Daniels. `?distance_m=&time_s=` ou déduites du meilleur effort. |
| `GET` | `/athletes/{id}/estimates` | Estimations de terrain : VO2max, FC max par quatre formules, métabolisme de base. |
| `GET` | `/athletes/{id}/fueling` | Plan glucidique et hydrique. `?duration_s=7200&temp_c=28&humidity_pct=65` |

---

## Montres

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/devices/providers` | État des trois connecteurs, comptes reliés, URL à déclarer, marche à suivre. **Ne renvoie jamais de jeton.** |
| `POST` | `/devices/{provider}/config` | Enregistre `client_id`, `client_secret`, `redirect_uri`. |
| `GET` | `/devices/{provider}/authorize?athlete_id=N` | Démarre l'autorisation (redirection 302, ou `&json=true` pour obtenir l'URL). |
| `GET` | `/devices/{provider}/callback` | Reçoit le retour d'autorisation. |
| `POST` | `/devices/{provider}/sync` | Synchronise un athlète (`?athlete_id=`) ou tous. `?days=30` |
| `DELETE` | `/devices/{provider}/accounts/{athlete_id}` | Délie un compte. |
| `GET` | `/devices/sync-log` | Journal des synchronisations. |
| `GET` | `/devices/hardware` | Matériel identifié dans les fichiers importés. |
| `POST` | `/webhooks/{provider}` | Point d'entrée des notifications push. |
| `GET` | `/webhooks/{provider}` | Vérification d'URL (renvoie `challenge` si fourni). |

`provider` vaut `garmin`, `polar` ou `coros`.

---

## Système

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/health` | État du serveur et de la base. |
| `GET` `PATCH` | `/config` | Réglages publics : seuils, pondérations, identité. |
| `GET` `POST` | `/teams` · `DELETE /teams/{id}` | Équipes. |
| `GET` | `/admin/stats` | Volumétrie détaillée. |
| `POST` | `/admin/rebuild` | Recalcule agrégats quotidiens et alertes. |
| `POST` | `/admin/reanalyze` | Réanalyse toutes les séances d'un athlète. |
| `GET` | `/admin/backup` | Copie cohérente de la base (`VACUUM INTO`). |
| `GET` | `/admin/routes` | Liste des routes enregistrées. |
| `POST` | `/admin/seed` | Régénère le jeu de démonstration. |
| `DELETE` | `/admin/reset?confirm=true` | Efface toutes les données. |

---

## Accès depuis le réseau local

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/network` | Adresses de la machine, port servi, URL pour le téléphone, code d'accès, QR en SVG, mises en garde. |
| `POST` | `/network` | `{"enabled": true\|false}` — ouvre ou referme l'accès réseau. |
| `POST` | `/network/code` | Tire un nouveau code ; les appareils reliés devront rescanner. |
| `GET` | `/network/qr.svg` | QR code en image. Paramètres : `url`, `module`, `dark`, `light`. |

`GET /network` renvoie `requires_restart: true` quand l'accès est autorisé
mais que le serveur écoute encore sur `127.0.0.1` : il faut le relancer avec
`--lan` pour que le téléphone puisse l'atteindre. Le champ `code` reste
`null` tant que l'accès est fermé.

---

## Notes d'implémentation

**Le cache du navigateur** est de 30 secondes sur les `GET`, vidé à chaque
écriture. Ajoutez un paramètre quelconque pour le contourner en développement.

**La compression gzip** est appliquée aux réponses de plus de 1 ko lorsque
le client l'annonce.

**Les flux** sont stockés compressés (zlib sur du JSON compact) et
sous-échantillonnés à la demande par moyenne de bloc, ce qui préserve la
forme du signal — contrairement à un simple prélèvement d'un point sur N,
qui perdrait les pointes.

**L'authentification est volontairement minimale.** Tant que le serveur
écoute sur `127.0.0.1`, aucune n'est demandée : l'application est conçue pour
tourner sur la machine de l'entraîneur. Dès que l'accès réseau est activé
(`POST /network` ou `run.py --lan`), toute requête n'émanant pas de la boucle
locale doit présenter le code à six chiffres, en paramètre `?c=` ou dans le
cookie `athlytics_access` :

- une requête `/api/…` sans code reçoit `401` avec
  `{"detail": {"needs_code": true}}` ;
- une requête de page sans code reçoit la page de saisie, autonome (ni CSS ni
  JavaScript du site, puisqu'elle précède l'autorisation) ;
- un `?c=` correct pose le cookie (`HttpOnly`, `SameSite=Lax`) puis redirige
  vers la même adresse sans le paramètre, pour que le code ne reste pas dans
  l'historique du téléphone ;
- après cinq échecs, une temporisation s'installe par adresse IP et double à
  chaque essai (plafond : cinq minutes), signalée par un `429` portant
  `retry_after`.

C'est une barrière d'usage, pas un chiffrement : les échanges restent en
HTTP simple. Pour une exposition réelle, placez l'application derrière un
reverse proxy en HTTPS.
