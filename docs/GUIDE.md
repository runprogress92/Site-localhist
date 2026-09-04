# Guide d'utilisation

Ce guide suit l'ordre dans lequel on prend l'outil en main : d'abord faire
entrer des données, puis les lire, puis planifier.

---

## 1. Créer un athlète

**Vue d'ensemble → aucun athlète ?** Le jeu de démonstration se génère au
premier lancement. Pour partir d'une base vide :

```bash
python3 run.py --reset
```

Ensuite, `POST /api/athletes` depuis l'interface (ou l'API). Renseignez au
minimum le prénom, le nom, le sexe et la date de naissance : le sexe
détermine les coefficients du TRIMP de Banister et les normes de VO2max,
l'âge sert aux estimations de FC maximale.

## 2. Renseigner le profil physiologique

**Fiche athlète → Physiologie → Mettre à jour le profil.**

C'est l'étape qui conditionne la qualité de tout le reste. Les champs qui
comptent le plus :

| Champ | Sert à | Comment l'obtenir |
|---|---|---|
| **FC au second seuil (LT2)** | Zones de FC, hrTSS | Moyenne de FC sur un contre-la-montre de 30 min, ou test lactate |
| **FC maximale** | Zones, TRIMP | Test progressif maximal — l'estimation par l'âge a une erreur type de 6 à 11 bpm |
| **FC de repos** | TRIMP, réserve de FC | Moyenne des mesures au réveil sur une semaine |
| **FTP** | Zones de puissance, TSS | 95 % de la puissance moyenne sur 20 min, ou test de puissance critique |
| **Allure au seuil** | Zones d'allure, rTSS | Allure moyenne sur un 10 km, ou 1 heure de course |

Chaque enregistrement est **daté**. Les séances antérieures gardent les
seuils qui étaient les leurs — c'est ce qui permet de comparer une charge de
janvier à une charge de juin. Cochez « Réanalyser » pour recalculer les
séances postérieures à la date d'effet.

## 3. Faire entrer les séances

Trois chemins, cumulables :

1. **Glisser-déposer** des fichiers `.fit`, `.tcx` ou `.gpx`
   (**Séances → Importer**). Fonctionne immédiatement, sans clé d'API.
2. **Connexion directe** à Garmin, Polar ou COROS (**Montres**), après
   inscription au programme développeur de la marque.
3. **Saisie manuelle** d'un RPE sur une séance sans capteur — la charge est
   alors estimée par la méthode de Foster.

## 4. Mettre en place le relevé quotidien

**Bien-être du jour.** C'est le geste qui rapporte le plus pour le temps
qu'il coûte. Deux minutes par athlète et par matin suffisent :

- **VFC (RMSSD)** au réveil, si l'athlète dispose d'une montre ou d'une
  application qui la mesure ;
- **FC de repos** ;
- **durée de sommeil** ;
- **quatre à six curseurs** de ressenti sur l'échelle de Hooper-Mackinnon
  (1 = très bon, 7 = très mauvais).

Le score de disponibilité se calcule dès qu'une seule de ces informations
est disponible. Il gagne beaucoup en pertinence après trois semaines : c'est
le temps qu'il faut pour établir les références personnelles.

## 5. Lire la charge

**Fiche athlète → Charge & forme.**

Le graphique du haut porte la condition (aire bleue) et la fatigue (ligne
rouge) ; celui du bas, la forme. La question utile n'est pas « quel est mon
TSB aujourd'hui » mais « où va-t-il ». Trois lectures :

- **La condition monte-t-elle ?** Une progression de 3 à 7 points de CTL par
  semaine est soutenable. Au-delà de 8, l'alerte se déclenche.
- **La forme suit-elle un cycle ?** Une alternance charge/décharge dessine
  des vagues. Une forme plate et durablement négative signale une charge
  entretenue sans jamais absorber.
- **Le ratio A:C reste-t-il dans la bande verte ?** 0,80 à 1,30. Un pic
  au-dessus de 1,50 mérite une semaine de stabilisation avant toute nouvelle
  hausse.

## 6. Vérifier la distribution d'intensité

Même onglet, en bas. Le graphique en trois zones (sous LT1 / zone grise /
au-dessus de LT2) et l'indice de polarisation répondent à une question
précise : **le volume facile est-il vraiment facile ?**

L'erreur la plus fréquente chez l'athlète assidu est la dérive vers la zone
intermédiaire — trop dur pour récupérer, trop facile pour progresser. Un
indice supérieur à 2,00 avec plus de 70 % du temps en aisance correspond à
la distribution la mieux documentée chez les athlètes d'endurance de haut
niveau.

## 7. Planifier

**Fiche athlète → Planification.**

- **Générer une semaine** produit une trame polarisée à partir d'une charge
  hebdomadaire cible : deux séances de qualité, une sortie longue, le reste
  en aisance, un jour de repos.
- **Rapprocher du réalisé** associe automatiquement chaque séance prévue à
  la séance effectivement faite le même jour, et calcule un taux de
  conformité.
- **Simulation d'affûtage** cherche la charge quotidienne qui amène la forme
  à la valeur visée le jour de l'objectif. Elle maintient la charge jusqu'à
  deux semaines de l'échéance, puis réduit — réduire trop tôt fait perdre la
  condition avant la course.

## 8. Analyser une séance

Cliquez sur n'importe quelle séance. Les pistes partagent un curseur : en
survolant la puissance, vous lisez simultanément la fréquence cardiaque, la
réserve W′ et l'altitude au même instant.

Trois chiffres à regarder en priorité :

- **Le facteur d'intensité** situe la séance : sous 0,65 c'est de la
  récupération, au-delà de 0,95 c'est du seuil.
- **Le découplage** dit si la base aérobie tient : sous 5 %, le rapport
  intensité/fréquence cardiaque est resté stable d'un bout à l'autre.
- **L'indice de variabilité** révèle un effort haché : au-delà de 1,10, la
  puissance moyenne sous-estime nettement le coût réel.

## 9. Réagir aux alertes

Les alertes de la vue d'ensemble portent toutes leur seuil et leur valeur.
Elles ne se substituent pas à votre jugement, mais elles vous font gagner le
temps du balayage.

| Alerte | Réaction habituelle |
|---|---|
| Ratio A:C > 1,50 | Stabiliser la charge une semaine, sans la baisser brutalement |
| Monotonie > 2,0 | Creuser l'écart entre séances dures et faciles, ajouter un jour de repos |
| VFC durablement basse | Alléger l'intensité 48 à 72 h, chercher une cause hors entraînement |
| FC de repos +5 bpm | Vérifier sommeil, hydratation, début d'infection |
| Dette de sommeil | Le levier le plus rentable, et le plus souvent négligé |

## 10. Sauvegarder

**Réglages → Télécharger une sauvegarde.** Le fichier obtenu est une copie
cohérente de la base ; il se remet en place en le renommant
`data/athlytics.db`.

---

## Raccourcis clavier

| Touche | Action |
|---|---|
| `/` | Recherche |
| `g` puis `d` | Vue d'ensemble |
| `g` puis `c` | Calendrier |
| `g` puis `s` | Séances |
| `g` puis `a` | Comparaison |
| `g` puis `b` | Bien-être |
| `g` puis `m` | Montres |
| `g` puis `r` | Réglages |
| `Échap` | Fermer une fenêtre |
