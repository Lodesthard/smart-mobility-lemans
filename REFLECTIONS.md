# Réflexions — Smart Mobility Le Mans

Données utilisées : GTFS statique SETRAM téléchargé le 2026-11-03, snapshots GTFS-RT
du 2026-11-03 entre 07:45 et 07:48 UTC (08h45–08h48 heure de Paris, heure de pointe).

---

## 1. Sous-questions faciles vs. difficiles (prédiction avant de construire) — *Réflexion 1*

La question métier se découpe en trois sous-questions :

- **« Où l'offre est-elle faible ? »** Je m'attendais à ce que ce soit facile : le
  GTFS statique liste tous les passages prévus, il suffit de compter par arrêt puis par
  commune.
- **« Où y a-t-il un écart entre offre et demande ? »** Prévu difficile : il n'existe
  pas de données de fréquentation ouvertes, donc tout repose sur un proxy (la
  population) et sur des choix de rattachement géographique.
- **« Quand intervenir ? » (retards récurrents, heures critiques)** Prévu impossible
  le premier jour : le GTFS-RT n'a pas d'historique, un snapshot ne dit rien de ce qui
  est *récurrent*. Il faut que le pipeline tourne plusieurs semaines.

## 2. Pourquoi le GTFS statique n'est pas rafraîchi toutes les 15 minutes (prédiction)

Le GTFS statique est un **horaire théorique** publié pour une période de plusieurs
mois. Il ne change que lorsque SETRAM publie une nouvelle grille (changement de
saison, vacances, travaux). Le retélécharger toutes les 15 minutes reviendrait à
télécharger ~2,4 Mo et recalculer 200 000 lignes 96 fois par jour pour obtenir 96 fois
le même résultat, et à générer des commits vides ou du bruit dans l'historique git.

## 3. Jointure sur des identifiants typés automatiquement

Si `pandas` infère les types fichier par fichier, une colonne `stop_id` qui ne contient
que des valeurs comme `1001` devient `int64`, tandis que la même colonne dans un autre
fichier qui contient aussi `FLEX-381` reste `object` (texte). Conséquences :

- soit la jointure échoue bruyamment (`ValueError: You are trying to merge on int64
  and object columns`) — le meilleur cas ;
- soit, si l'on a converti à la main ou si les deux colonnes sont `object` mais avec
  des représentations différentes (`1001` vs `"1001"`, ou `"0123"` devenu `123`), la
  jointure **réussit sans erreur mais ne trouve aucune correspondance** : en `how="left"`
  les coordonnées deviennent `NaN`, puis le `dropna(subset=["stop_lat"])` du script
  supprime ces arrêts silencieusement. On obtient un résultat plausible mais faux.

D'où `dtype=str` partout : un identifiant est une étiquette, pas un nombre.

## 4. Volume : journalisation par arrêt vs. par ligne — *Réflexion 3*

Ordres de grandeur pour un semestre de 12 semaines, un snapshot toutes les 15 min :

- snapshots : 96/jour × 84 jours ≈ **8 000 snapshots** ;
- **par arrêt** : ~5 000 à 6 500 mises à jour par snapshot (6 533 mesurées sur notre
  snapshot de 07:48 UTC) → **≈ 50 millions de lignes**, soit plusieurs Go en CSV —
  ingérable dans un dépôt git ;
- **par ligne** : 27 à 40 lignes par snapshot → **≈ 220 000 à 320 000 lignes**. Notre
  fichier réel fait ~34 octets par ligne, soit ~10 Mo pour le semestre.

Question rendue plus difficile par l'agrégation par ligne : **« quels arrêts ou quels
tronçons accumulent les retards ? »**. Un planificateur veut savoir *où* sur la ligne
le retard naît (un carrefour, un pont, un tronçon sans site propre) pour décider d'une
voie bus ou d'une priorité aux feux. Une moyenne par ligne ne peut pas répondre : elle
mélange les tronçons fluides et le point noir.

## 5. Alternative à l'encodage « en avance = vert, en retard = rouge » — *Réflexion 4*

Le graphique actuel colore en vert tout ce qui est en avance, quel que soit l'écart.
Or un bus qui passe 2 minutes en avance fait rater le bus à un voyageur arrivé à
l'heure : pour lui c'est **pire** qu'un retard de 2 minutes (il attend le suivant).

Proposition : un encodage **divergent centré sur la ponctualité** :

- vert pour l'intervalle « à l'heure » (par ex. de −1 min à +3 min, la convention
  courante des opérateurs) ;
- bleu/violet de plus en plus saturé pour l'**avance** au-delà de −1 min ;
- orange puis rouge pour le **retard** au-delà de +3 min ;
- et, mieux encore, ne plus tracer la *moyenne* mais le **taux de passages hors de la
  fenêtre** [−1 min ; +3 min], car la moyenne compense avances et retards.

Ce que ça change dans nos données réelles : T2 (−45 s en moyenne), 22 (−35 s),
24 (−37 s) et 33 (−54 s) apparaissent en vert vif aujourd'hui, comme les « meilleures »
lignes. Avec mon encodage, elles seraient signalées comme lignes **en avance** à
réguler (temps d'attente aux points de régulation, horaires trop larges), et non comme
des modèles. Inversement C4 (moyenne +236 s mais médiane 0 s) apparaît comme la pire
ligne alors que la majorité de ses passages sont à l'heure : le problème est concentré
sur quelques courses. La décision change : on n'intervient pas sur « la ligne C4 »
mais sur certaines courses/heures.

## 6. Les deux moitiés du décalage de cadence — *Réflexion 5*

- **Statique toutes les 15 min = gaspillage.** L'horaire théorique ne change que
  quelques fois par an. La bonne cadence est celle de la source : mensuelle suffit
  (une nouvelle grille est publiée avec plusieurs semaines d'avance), et un lancement
  manuel couvre les changements imprévus. Notre propre run le confirme dans l'autre
  sens : le jeu de données data.gouv.fr récupéré le 3 novembre est **périmé** (services
  semaine valides jusqu'au 30/10, alors que setram.fr annonce de nouveaux horaires
  « à partir du 02/11 »). Le rythme du statique dépend de l'éditeur, pas de nous ; le
  rafraîchir plus souvent n'aurait rien changé.
- **Temps réel mensuel = inutile.** Un retard est un état éphémère : il existe pendant
  quelques minutes puis disparaît. Un snapshot par mois donnerait 12 points par an, pris
  à une heure arbitraire (04:00 UTC = réseau quasi vide), sans aucune information sur
  l'heure de pointe, la variabilité jour à jour ou la récurrence. On ne pourrait ni
  détecter un incident en cours ni construire des profils horaires. La cadence doit
  être de l'ordre de la durée de vie du phénomène mesuré (ici 15 min, voire moins).

Ma prédiction (point 2) avait la première moitié ; je n'avais pas pensé au fait que la
fraîcheur du statique est contrainte par l'éditeur.

## 7. Vérification d'une ligne retardée face à la réalité — *Réflexion 6*

Snapshot de 07:48 UTC (08h48 à Paris, mardi, heure de pointe) : **C4** est la ligne
la plus en retard (moyenne 220–236 s selon le snapshot, max 2 616 s soit ~44 min).

Ce que j'ai vérifié :

- **Bandeau « Info trafic à 08:45 » de setram.fr** : il liste les lignes C4, 5, 8, 10A,
  10B, 24, 28, 32 (et 160, 161). C4 et 5, nos deux lignes les plus en retard, y
  figurent. Les lignes 8, 10A, 10B, 24, 28 et 32 sont exactement celles qui ont des
  arrêts `SKIPPED` dans notre snapshot. Les données correspondent donc bien à une
  perturbation réelle signalée par l'opérateur (le site ne donne pas le détail de la
  cause sur la page d'accueil).
- **Distribution de C4** : médiane **0 s**. Les courses C4 ont pour retard maximal :
  2 616, 2 130, 1 803, 1 740, 1 740, 1 560, 736 s… puis 14 courses quasi à l'heure. La
  moyenne est tirée par 6 courses. Ligne 5 : médiane +60 s, retard modéré et étalé,
  typique de la congestion de pointe.
- **Hypothèse sur les valeurs extrêmes** : des retards ronds (1 740 s = 29 min tout
  rond, deux fois) ressemblent moins à des bus réellement bloqués qu'à des courses
  décalées/déviées dont les prédictions sont recalées sur la course suivante. C'est
  cohérent avec une perturbation (déviation) annoncée sur le site, mais l'ampleur exacte
  est probablement en partie un **artefact de prédiction**. Le contexte local va aussi
  dans ce sens : la fête foraine d'octobre/novembre est en cours et le réseau vient de
  changer d'horaires le 02/11.

Conclusion : le signal « C4 et 5 sont perturbées » est réel ; le chiffre « 4 minutes de
retard moyen sur C4 » est trompeur. Il faut afficher la médiane ou un taux de courses
en retard en plus de la moyenne.

## 8. Cas où la population trompe comme proxy de la demande — *Réflexion 7*

Exemple concret : une commune peu peuplée qui accueille un **grand générateur de
déplacements** — zone d'activités, hôpital, centre commercial, campus. Les gens qui y
vont n'y habitent pas. Inversement, une commune résidentielle peuplée mais très
motorisée (pavillonnaire) peut avoir une demande TC faible. Au Mans même, le cas
d'école est le **campus de l'Université** (et les 24 Heures du Mans pour la demande
événementielle, concentrée sur quelques jours au Sud de l'agglomération, vers
Arnage/Mulsanne).

## 9. Métrique offre / population et commune où elle trompe — *Réflexion 8*

**Métrique** : nombre de passages programmés (bus + tram) aux arrêts de la commune,
un jour de semaine représentatif, pour 1 000 habitants.

Résultat réel (mardi 2026-09-01, 1 011 arrêts) :

| Rang | Commune | Population | Arrêts | Passages/jour | Passages / 1 000 hab. |
|---|---|---|---|---|---|
| 1 | La-Chapelle-Saint-Aubin | 2 319 | 75 | 3 729 | **1 608** |
| 2 | Coulaines | 8 226 | 120 | 7 252 | 882 |
| 3 | Rouillon | 2 666 | 46 | 1 949 | 731 |
| … | | | | | |
| 7 | **Le Mans** | 148 876 | 389 | 32 171 | **216** |
| … | | | | | |
| 20 | Chaufour-Notre-Dame | 1 187 | 4 | 64 | 54 |

**Commune où le classement est faux : La-Chapelle-Saint-Aubin, n°1.** Une commune
périurbaine de 2 300 habitants n'est pas 7 fois mieux desservie que Le Mans. En
regardant les arrêts qui lui sont attribués, on trouve **Université** (418 passages),
**Campus-Ribay**, **Haute Venelle-Clinique du Pré**, **Cadran-Épine** : c'est le campus
de l'Université du Mans et le terminus du tram T1, situés **sur la commune du Mans**.
Le script rattache chaque arrêt au *centre de commune le plus proche* ; comme Le Mans
est très étendue, ses quartiers périphériques sont plus proches du centre des communes
voisines que de la place de la mairie du Mans. Même phénomène pour Coulaines (Maillets,
Zamenhof) et Rouillon (St-Georges, Folleray, St-Joseph).

Deux erreurs se cumulent donc : (1) le **rattachement géographique** déplace l'offre du
Mans vers ses voisines, (2) le **dénominateur** compte des habitants alors que la
demande du campus vient d'étudiants non résidents. Correction : rattacher les arrêts
par point-dans-polygone sur les contours communaux officiels (IGN Admin Express) au
lieu du centre le plus proche.

Deuxième piège visible dans la sortie : pour Fay (44 %), Fatines (48 %) et
Chaufour-Notre-Dame (45 %), un seul arrêt porte près de la moitié de l'offre ; le score
de ces communes dépend d'un seul point et ne dit rien de la couverture du reste du
territoire. Le tableau du dashboard les signale en orange (colonne « busiest stop
share »).

Enfin, en construisant cette vue j'ai trouvé un **bug dans le script fourni** : il ne
retenait qu'un seul `service_id` (le motif du mardi à la plus longue validité). Or
SETRAM sépare bus (`B-…`) et tram (`T-…`) dans des services de même durée, et le
départage gardait les bus : **T1 et T2 étaient absents** de `stops_frequency.csv`
(798 arrêts au lieu de 1 011). Le script prend maintenant tous les services actifs le
mardi le plus chargé.

## 10. Agréger les retards au niveau arrêt sans exploser l'historique — *Réflexion 9*

Approche :

1. **Dédupliquer avant d'agréger.** Une même course × arrêt apparaît dans des dizaines
   de snapshots successifs (prédictions qui s'affinent). On ne garde que la dernière
   observation de chaque couple (`trip_id`, `stop_id`, date de service), c'est-à-dire
   la valeur la plus proche du passage réel. Pendant la journée, ce fichier de travail
   reste un tampon non versionné (cache Actions ou fichier écrasé), pas un log append.
2. **Agréger par cases fixes.** Une fois par jour, on réduit ce tampon à une ligne par
   (`stop_id`, type de jour [semaine/samedi/dimanche], tranche horaire [ex. 5 tranches :
   pointe matin, creuse, pointe soir, soirée, nuit]) avec des **compteurs additifs** :
   `n_obs`, `sum_delay`, `n_late_3min`, `n_early_1min`. Comme ce sont des sommes, on
   peut les cumuler jour après jour sans garder le détail, et recalculer moyennes et
   taux à tout moment.
3. **Taille** : ~1 000 arrêts × 3 types de jour × 5 tranches ≈ 15 000 lignes par mois,
   soit < 1 Mo par mois — au lieu de ~16 millions de lignes brutes.

Ce qui est perdu : la distribution fine (percentiles) et la chronologie d'un incident
précis. Si on veut la médiane, on peut ajouter des compteurs par classe de retard
(histogramme à 6 classes) qui restent additifs.

## 11. Bilan : prédictions vs. réalité — *Réflexion 10*

- **Répondable aujourd'hui** : *où l'offre programmée est concentrée* (Gares,
  Jaurès-Pavillon, axes tram) et *quelles lignes sont perturbées en ce moment* (C4, 5,
  confirmées par l'opérateur). C'était bien la partie facile, **à condition** de
  vérifier les données : le script fourni excluait silencieusement le tram et le GTFS
  statique était périmé de 4 jours. « Facile » ne voulait pas dire « fiable sans
  contrôle ».
- **Demandait des choix de jugement** : la définition de « jour représentatif », la
  métrique d'offre, le rattachement arrêt → commune, le proxy population, et
  l'encodage avance/retard. Ce sont ces choix, pas le code, qui ont le plus changé la
  réponse : le rattachement au centre le plus proche place La-Chapelle-Saint-Aubin
  première et Le Mans septième, ce qui conduirait à prioriser les mauvais territoires.
  J'avais sous-estimé ce point : je pensais que la difficulté de l'écart offre/demande
  venait du proxy population, alors que la géographie pèse au moins autant.
- **Nécessite des semaines d'historique** : *quand* intervenir (heures et jours où les
  retards sont récurrents, lignes structurellement en retard vs. incident ponctuel
  comme celui de C4 aujourd'hui) et toute prédiction. Un seul matin montre que la
  moyenne d'un snapshot peut être dominée par 6 courses ; seule l'accumulation permet de
  distinguer le récurrent du ponctuel. Cette prédiction initiale était juste.
