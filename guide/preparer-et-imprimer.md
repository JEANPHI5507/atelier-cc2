# Préparer et imprimer

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/prepare-and-print.md)

Tout se passe dans l'onglet **Atelier**, en trois étapes guidées à droite de la vue 3D : **1. Couleurs**, **2. Taille et
réglages**, **3. Trancher**, puis **Imprimer**. Les mêmes opérations existent en ligne de commande
([Ligne de commande](ligne-de-commande.md)).

## La bibliothèque

À gauche : tes modèles et les fichiers prêts à imprimer.

- **Ajouter** : glisser-déposer (ou cliquer) des STL, 3MF, STEP, OBJ, GLB, GLTF, PLY, OFF, DAE, des zip de modèles ou
  du G-code, ou **Importer depuis un lien**. Un STEP (fichier CAD) devient un GLB à l'import ; un zip déplie tous les
  modèles qu'il contient. Le lien peut viser un fichier, un zip de modèles, ou une page publique qui propose un fichier à télécharger.
  Les sites qui ne donnent leurs fichiers qu'à un compte connecté (MakerWorld par exemple) ne marchent pas par lien :
  télécharge le fichier, puis dépose-le. Un fichier ajouté ne remplace jamais un fichier existant (« modèle (2).stl »).
- **Vues** : Tout, Modèles, **Prêts** (les G-code, rangés sous le modèle dont ils viennent). Tri et recherche dans le
  menu « ⋯ ».
- **Fiche d'un G-code** : modèle d'origine, qualité, durée, grammes, coût, couleurs, et la mention « sur la CC2 » s'il
  est déjà dans l'imprimante.
- **Renommer**, **sélectionner plusieurs fichiers**, **faire le ménage** (fichiers techniques et G-code orphelins,
  avec la place gagnée) : menu « ⋯ ».
- **Percer ou ajouter une forme** (bouton cube en haut de la fiche du modèle) : un cylindre, un pavé ou une boule, à
  percer dans le modèle (un trou pour une vis, un aimant, une ficelle), à ajouter (un plot, un socle, dans une couleur
  du modèle ou une nouvelle) ou à garder seul (ce que la forme et le modèle ont en commun). La forme apparaît en
  transparence sur le modèle pendant qu'on la règle (taille, sens, décalage depuis son centre). Les couleurs du modèle
  sont gardées ; un nouveau fichier est créé, l'original reste intact.

## La vue 3D

Le modèle est montré **à la taille où il sera imprimé**, sur le plateau de la CC2 (marquage officiel d'Elegoo), dans la
couleur de la bobine qui l'imprimera.

- Vues **3D**, **Face**, **Dessus**, **Côté**, **Plateau** (tout le plateau), recentrer, plein écran.
- **Surplombs** : colore en rouge, en direct, les zones qui auront besoin de supports.
- **Cotes** : dimensions à la taille d'impression.
- **+ Pièce** : ajoute une autre pièce de la bibliothèque sur le même plateau. L'atelier crée un nouveau modèle (« cube +
  pion ») avec les deux côte à côte, chacune avec ses couleurs (4 au plus en tout, une couleur commune partage la
  bobine) ; le modèle d'origine ne change pas. Recommence pour en mettre une troisième.
- **Déplacer** : touche une pièce pour la choisir (cadre orange) et glisse-la pour la déplacer ; elle s'arrête au bord
  du plateau. Le cadre en bas à gauche règle **sa taille** (10 à 500 %, raccourcis 50, 75, 100, 150 %) : elle grandit
  ou rétrécit sur place, posée sur le plateau. Le tranchage reprend les mêmes places et tailles. **Regrouper** remet
  tout comme au départ.
- **Supprimer cette pièce** (dans le cadre de la pièce choisie) : elle quitte le plateau dans un nouveau modèle ; les
  autres gardent leurs places et leurs tailles, et le modèle d'origine reste dans la bibliothèque.
- Tourner ou coucher la pièce la garde à sa place sur le plateau.
- Le **coin interdit** de la CC2 (avant droit, 10 × 20 mm) est en rouge : l'atelier n'y pose jamais rien.
- Après le tranchage, l'onglet **Tranchage** montre les vrais trajets couche par couche (curseur, lecture, couche seule,
  supports en orange, tour d'essuyage), chacun masquable.

## 1. Couleurs

L'atelier lit les couleurs du modèle (3MF peints de MakerWorld, Printables, OrcaSlicer ou Bambu Studio ; GLB/GLTF ;
OBJ+MTL ; PLY colorés) et les **associe aux bobines réellement chargées dans le CANVAS** : à chaque couleur la bobine
la plus proche à l'œil, sans laisser une bobine libre pendant que deux couleurs s'en partagent une. Tout reste
modifiable : couleur par couleur, ou **Modifier**.

- Plus de 4 couleurs : les teintes proches sont regroupées.
- Un modèle **sans couleur** s'imprime avec la bobine déjà engagée dans le CANVAS (pas de changement inutile).
- Une couleur trop éloignée de toutes les bobines, ou un mélange PLA + PETG, est signalé.
- **Tes choix sont retenus** : la bobine que tu donnes à une couleur est réappliquée à la prochaine préparation du
  même modèle, même si les bobines ont changé de place dans le CANVAS (tant qu'elle est encore chargée là ou ailleurs).
- Sous chaque bobine chargée : **le filament qu'il reste** (~ g), en alerte quand elle est presque vide — plus besoin
  d'attendre la vérification du lancement pour le découvrir.
- **Le besoin de chaque couleur est estimé** avant même de trancher (à partir du volume du modèle et de l'usage
  choisi) : une bobine qui n'en aura pas assez apparaît en rouge immédiatement. L'estimation **se corrige toute
  seule** à chaque vraie impression : plus tu imprimes, plus elle est juste.
- **Assembler** (en haut de la bibliothèque) : un modèle livré en plusieurs fichiers, un par couleur, devient un seul
  modèle multicolore.
- **Pinceau** (vue 3D, tous les modèles) : retoucher les couleurs à la main, dans les couleurs du modèle (un STL
  sans couleur restera d'une seule teinte).
- **Mesurer** (vue 3D, tous les modèles) : deux points touchés sur la pièce, la distance entre eux s'affiche en mm.
- **Supports** (vue 3D, tous les modèles) : peindre « Support ici » (vert), « Jamais de support ici » (rouge) et
  « Couture ici » (bleu, l'endroit où commence chaque couche), la gomme efface. Des supports peints sans avoir demandé de
  supports : il n'y en a que là. Les zones sont gardées à côté du modèle, le fichier lui-même ne change pas.

## 2. Taille et réglages

### Optimiser pour la CC2

Le gros bouton en haut fait en une fois ce qu'il faut pour que le fichier s'imprime bien sur la CC2 : il répare le
maillage s'il est ouvert (sur une copie), donne une vraie taille à un modèle IA sans unité, choisit la meilleure face à
poser, puis applique les conseils (supports, bordure, découpe). Chaque changement est expliqué ; **Annuler
l'optimisation** remet tout comme avant.

### À quoi sert la pièce ?

| Choix | Ce que ça change |
|---|---|
| **Décoratif** (par défaut) | même aspect, intérieur allégé (remplissage « éclair » 8 %) : jusqu'à −55 % de filament |
| **Solide** | 4 parois, remplissage gyroïde, paroi extérieure précise (cotes justes) ; proposé d'office pour les boîtes, crochets, organiseurs |
| **Détaillé** | couches de 0,12 mm |
| **Rapide** | couches de 0,24 mm |
| **Profil Elegoo** | le profil d'origine, sans rien changer |

Exemple mesuré : une figurine de 95 mm passe de 62 g / 3 h 35 (profil Elegoo) à 26 g / 2 h 13 en Décoratif.

### Le reste de l'étape

- **Hauteur finale** en mm (vide : taille d'origine ; 60 mm proposés pour un modèle IA sans unité). Sous les
  positions : **miroir** gauche ↔ droite et échelle par axe (X, Y, Z en %).
- **Comment poser la pièce** : six vignettes (telle quelle, couchée vers l'avant ou l'arrière, sur un côté, à
  l'envers) ; la position **conseillée** a le moins de surplombs et une vraie surface au sol. « Tourner sur le
  plateau » la pivote à plat.
- **Découper en pièces** si c'est plus grand que le plateau : coupes aux endroits les plus fins (cou, taille…), trous
  de chevilles Ø 5 mm de part et d'autre, un G-code par pièce plus un pour les chevilles. « voir la découpe » montre
  les pièces en vue éclatée. Le jeu des chevilles se règle dans l'onglet Démarrage.
- **Plateau** : PEI texturé (livré avec la CC2, 60 °C en PLA) par défaut ; PEI lisse, froid ou ingénierie au choix.
- **Supports** : aucun, en arbre (organiques, s'enlèvent bien), en arbre fins, solides, ou colonnes ; « seulement
  depuis le plateau » pour que rien ne s'appuie sur la pièce.
- **Pause à la hauteur** (mm) : la CC2 se met en pause à cette hauteur, pour glisser un aimant, un écrou, ou changer
  de couleur à la main. Plusieurs hauteurs séparées par « ; ». La tête se gare et la buse baisse à 100 °C ; reprends
  depuis l'atelier ou l'écran.
- **Exemplaires** sur le plateau (jusqu'à 50, en grille). Chaque pièce est marquée dans le G-code : si l'une rate, on
  peut l'abandonner et finir les autres.
- **Réglages avancés** (vide = valeur du profil CC2) : parois, couches pleines, motif de remplissage, motif du dessus,
  une seule paroi sur le dessus (déjà active dans le profil CC2), hauteur de couche variable (automatique par défaut, sauf en usage « Profil Elegoo » : couches plus fines là où
  la surface est en pente douce, pour des dômes et arrondis plus lisses ; sans effet sur une pièce droite), paroi extérieure précise (cotes justes pour
  les pièces qui s'emboîtent), couture, lissage, bordure, radeau, angle des supports, ordre d'impression (couche par couche, ou pièce par pièce — voir Multicolore), températures, avance de
  pression, débit… Chaque valeur est vérifiée avant d'aller au slicer.

### Multicolore

| Mode | Principe | Quand |
|---|---|---|
| **Équilibré** (par défaut) | tour d'essuyage + purge dosée selon les couleurs | couleurs nettes, même sur un modèle qui change souvent |
| **Économie** | pas de tour d'essuyage, purge dosée selon les couleurs | le moins de filament ; bien pour peu de changements et des couleurs proches |
| **Qualité** | tour + purge d'origine d'OrcaSlicer | couleurs très contrastées, maximum de propreté |
| **Sans purge** | changement de bobine seul | essais ; mélange visible entre couleurs |

La purge se fait dans la goulotte du CANVAS. Elle est dosée **en volume réel** selon le passage de couleur (du rouge au
blanc il en faut plus que du blanc au rouge), ce qui évite le marbrage. Mesuré sur un perroquet de 60 mm en 4
couleurs : 13 h 13 et ≈ 200 g en Qualité, 8 h 26 et ≈ 38 g en Économie. Si un bilan a signalé des couleurs qui bavent
ou des gouttes sur cette pièce, le tranchage suivant purge le pire cas à chaque changement, quel que soit le mode.

En Équilibré et Qualité, la tour a une bordure de 8 mm et la buse se lève de 0,8 mm en passant dessus : avec du PLA
Silk, le fil qui coule après chaque purge fait des boucles sur la tour, et la buse les accrochait jusqu'à la renverser.

**Simplifier les couleurs** (Non, Léger, Fort) : une tache de couleur presque absente d'une couche (moins de 3 %, ou
10 % en Fort) prend la couleur dominante de cette couche. Moins de changements, moins de purge, sans différence
visible en Léger.

Les leviers qui comptent vraiment : **moins de changements** (couches plus épaisses, couleurs simplifiées) et
**plusieurs pièces par plateau**, car les changements se font couche par couche pour toutes les pièces à la fois.
Le résultat prévient au-delà de 150 changements.

**Ordre d'impression : pièce par pièce** (Réglages avancés) : le plateau est tranché une pièce entière après
l'autre, les pièces regroupées par couleur, au lieu que toutes avancent couche par couche. Une couleur imprime
tout ce qui la porte avant de céder la place : sur deux pièces de couleurs différentes bien espacées, mesuré à
l'atelier, 2 changements et 28 min au lieu de 101 et 2 h 21. Sans tour d'essuyage dans cet ordre, le premier
millimètre après chaque changement fond les deux couleurs ; une pause à une hauteur tombe dans chaque pièce.
La CC2 impose sa géométrie : 65 mm d'écart entre pièces (la tête balaie tout autour de la buse en imprimant la
suivante) et 36 mm de haut au plus (la traverse passe au-dessus) — sinon le tranchage le dit, et on les écarte
en mode Déplacer. Ignoré pour plusieurs exemplaires d'un même modèle (couche par couche, ils partagent chaque
changement) et si toutes les pièces portent les mêmes couleurs.

## 3. Trancher

**Trancher** lance OrcaSlicer avec les profils Elegoo de la CC2. Le résultat donne la durée, les grammes et le coût
(purge comprise) par bobine, le nombre de changements de couleur, les températures de buse et de plateau du profil
(optimales pour le filament choisi), et les points à surveiller.

- Le **conseiller** regarde la pièce telle qu'elle sera imprimée et prévient avant de perdre une bobine : parois trop
  fines, peu de contact avec le plateau, surplombs sans support, morceau en l'air, pièce haute et fine, maillage
  ouvert. Chaque point a un bouton qui applique la correction.
- **Comparer les options** tranche plusieurs variantes en arrière-plan (qualité, usage) et montre l'écart de filament,
  de coût et de temps ; « Choisir » applique la variante.
- Si OrcaSlicer refuse une pièce qui flotterait sans support, l'atelier recommence avec des supports en arbre et le dit.

## Assistant (étape 4)

L'**Assistant** vit maintenant **dans la vue 3D** : un panneau repliable en haut à droite, juste sous les boutons
de la vue — la pièce reste visible derrière lui (sur téléphone il est replié, une pique sur le titre le déplie).
Tu demandes avec tes mots, il agit lui-même sur le modèle
dans la bibliothèque — réparer, changer la hauteur ou l'échelle (miroir compris), faire pivoter, proposer la
meilleure pose, percer un trou d'aimant ou ajouter un socle, et même trancher pour annoncer la durée réelle.
Le cerveau est le CLI agent installé sur la machine (par défaut `vibe`, lancé hors écran à chaque message — aucune
clé API, il est déjà connecté à ton compte) : chaque action passe par le même code que les boutons de la page et
crée un nouveau fichier (l'original reste intact). Ses serveurs **MCP** restent accessibles : si Blender tourne
avec le pont « blender » (add-on *MCP for Blender*, voir [Blender](blender.md)), l'Assistant peut construire la
pièce en vraie CAO et l'exporter dans la bibliothèque. Repli possible sur l'API Mistral
(`[assistant] moteur = "api"` + `api_key`, voir [Configuration](configuration.md)).
La conversation suit le modèle ; un tour peut prendre quelques dizaines de secondes. Pendant qu'il travaille,
le journal s'affiche en direct dans la bulle grise sous le message : l'atelier sur la pièce (fiche,
redimensionner…), puis les appels de l'agent CLI hors écran (Blender : import, code, capture `look` du regard).

**Viser un endroit précis** : le bouton **Cibler** de la vue 3D transforme la souris en viseur — clique la
surface de la pièce pour poser un marqueur orange, règle son rayon dans la bulle qui apparaît sous la conversation,
puis écris ton message : l'agent reçoit les coordonnées exactes du point (repère du fichier, Z = hauteur) et le
rayon, et y porte son travail. Retirer le marqueur : le ✕ de la bulle, ou choisir un autre modèle.

**Mesurer sur la pièce** : le bouton **Mesurer** de la vue 3D pose deux points — touche un premier point de la
surface, un deuxième : la ligne tirée entre eux affiche la vraie distance en mm (diamètre d'un trou, entraxe de
deux trous…), même si tu tournes la vue. Un nouveau clic part d'un nouveau point ; resors du mode pour tout effacer.

Tout mesh que l'agent écrit lui-même dans la bibliothèque (export Blender…) est affiché tout seul dans la vue 3D :
la page la recharge dès qu'il annonce son travail, même si le fichier garde le même nom.

## Imprimer

**Imprimer** ouvre la fenêtre de lancement :

- **Quelle bobine pour chaque couleur** : proposée d'après les couleurs du G-code et le CANVAS, modifiable. C'est elle
  qui est envoyée à la CC2 (sans elle, la CC2 imprimerait T0 avec la bobine 1, T1 avec la 2…).
- **Plateau vérifié à la caméra** : quand le plateau est vide, clique « Le plateau est vide : mémoriser » une fois.
  Ensuite, avant chaque impression, l'atelier compare l'avant du plateau à cette photo (lumière allumée pour l'occasion)
  et bloque le lancement s'il reste une pièce. « Le plateau est vide » met la référence à jour en cas de doute (ombre,
  reflet).
- **Options de la machine** : niveler le plateau avant, vérifications de l'imprimante, timelapse de l'imprimante,
  disposition A/B. Les valeurs par défaut se règlent dans la carte « Machine » de l'onglet Imprimante.
- Grammes et coût, avec une alerte si une bobine ne suffira pas.

Si l'imprimante imprime déjà, **Ajouter à la file d'attente** garde le fichier pour après. Dans l'onglet Imprimante,
la carte **File d'attente** propose « Plateau vidé : lancer la suivante » dès que la pièce précédente est retirée.

## Créer sans CAO

Le bouton **Créer** (en haut de la bibliothèque) fabrique des pièces sur mesure, avec un aperçu 3D qui suit chaque
réglage :

| Pièce | Réglages |
|---|---|
| Boîte avec couvercle | longueur, largeur, hauteur, parois, jeu du couvercle, coins arrondis |
| Étiquette en relief (2 couleurs) | texte (plusieurs lignes), hauteur des lettres, relief, marge, trou pour l'accrocher |
| Crochet mural | largeur, hauteur du dos, profondeur, épaisseur, diamètre de vis |
| Organiseur à compartiments | dimensions, nombre de cases dans chaque sens, cloisons, fond |
| Bac Gridfinity | taille en cases de 42 mm, hauteur en unités de 7 mm, compartiments, aimants 6 × 2 mm, lèvre pour empiler |
| Plaque Gridfinity | taille en cases, aimants |
| Support de téléphone | largeur, inclinaison, épaisseur de l'appareil (coque comprise), dossier, passage du câble |
| Range-câbles | nombre et diamètre des câbles, pattes pour vis ou adhésif |
| Vis, écrou, rondelle, entretoise | filetage ISO de M3 à M10, longueur, jeu d'impression |
| Engrenage droit | nombre de dents, module, épaisseur, alésage, angle de pression |
| Porte-clés prénom (2 couleurs) | prénom, écriture, hauteur des lettres, relief |
| Décoration de Noël prénom | boule, étoile ou sapin, prénom, taille, relief |
| Lithophanie photo | ta photo, largeur, épaisseurs claire et foncée, cadre (impression debout, 100 % de remplissage) |

La pièce créée arrive dans la bibliothèque, prête à passer par les trois étapes.

## Après l'impression

Le **bilan** (galerie, ou bouton de la notification de fin) note ce qui n'allait pas ; la correction est proposée la
prochaine fois que tu prépares le même modèle. Voir [Suivre une impression](suivre.md).
