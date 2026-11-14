# Préparer et imprimer

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/prepare-and-print.md)

Tout se passe dans l'onglet **Atelier**, en trois étapes guidées à droite de la vue 3D : **1. Couleurs**, **2. Taille et
réglages**, **3. Trancher**, puis **Imprimer**. Les mêmes opérations existent en ligne de commande
([Ligne de commande](ligne-de-commande.md)).

## La bibliothèque

À gauche : tes modèles et les fichiers prêts à imprimer.

- **Ajouter** : glisser-déposer (ou cliquer) des STL, 3MF, OBJ, GLB, GLTF, PLY ou G-code, ou **Importer depuis un
  lien**. Le lien peut viser un fichier, un zip de modèles, ou une page publique qui propose un fichier à télécharger.
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
- **Assembler** (en haut de la bibliothèque) : un modèle livré en plusieurs fichiers, un par couleur, devient un seul
  modèle multicolore.
- **Pinceau** (vue 3D, modèles GLB, OBJ, PLY) : retoucher les couleurs à la main.
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
| **Solide** | 4 parois, remplissage gyroïde ; proposé d'office pour les boîtes, crochets, organiseurs |
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
  une seule paroi sur le dessus (déjà active dans le profil CC2), hauteur de couche variable (couches plus fines là où
  la surface est en pente douce, pour des dômes et arrondis plus lisses), paroi extérieure précise (cotes justes pour
  les pièces qui s'emboîtent), couture, lissage, bordure, radeau, angle des supports, températures, avance de
  pression, débit… Chaque valeur est vérifiée avant d'aller au slicer.

### Multicolore

| Mode | Principe | Quand |
|---|---|---|
| **Économie** (par défaut) | pas de tour d'essuyage, purge dosée selon les couleurs | la plupart des pièces |
| **Équilibré** | tour d'essuyage + purge dosée | si des gouttes ou des bavures apparaissent aux changements |
| **Qualité** | tour + purge d'origine d'OrcaSlicer | couleurs très contrastées, maximum de propreté |
| **Sans purge** | changement de bobine seul | essais ; mélange visible entre couleurs |

La purge se fait dans la goulotte du CANVAS. Elle est dosée **en volume réel** selon le passage de couleur (du rouge au
blanc il en faut plus que du blanc au rouge), ce qui évite le marbrage. Mesuré sur un perroquet de 60 mm en 4
couleurs : 13 h 13 et ≈ 200 g en Qualité, 8 h 26 et ≈ 38 g en Économie.

En Équilibré et Qualité, la tour a une bordure de 8 mm et la buse se lève de 0,8 mm en passant dessus : avec du PLA
Silk, le fil qui coule après chaque purge fait des boucles sur la tour, et la buse les accrochait jusqu'à la renverser.

**Simplifier les couleurs** (Non, Léger, Fort) : une tache de couleur presque absente d'une couche (moins de 3 %, ou
10 % en Fort) prend la couleur dominante de cette couche. Moins de changements, moins de purge, sans différence
visible en Léger.

Les leviers qui comptent vraiment : **moins de changements** (couches plus épaisses, couleurs simplifiées) et
**plusieurs pièces par plateau**, car les changements se font couche par couche pour toutes les pièces à la fois.
Le résultat prévient au-delà de 150 changements.

## 3. Trancher

**Trancher** lance OrcaSlicer avec les profils Elegoo de la CC2. Le résultat donne la durée, les grammes et le coût
(purge comprise) par bobine, le nombre de changements de couleur, et les points à surveiller.

- Le **conseiller** regarde la pièce telle qu'elle sera imprimée et prévient avant de perdre une bobine : parois trop
  fines, peu de contact avec le plateau, surplombs sans support, morceau en l'air, pièce haute et fine, maillage
  ouvert. Chaque point a un bouton qui applique la correction.
- **Comparer les options** tranche plusieurs variantes en arrière-plan (qualité, usage) et montre l'écart de filament,
  de coût et de temps ; « Choisir » applique la variante.
- Si OrcaSlicer refuse une pièce qui flotterait sans support, l'atelier recommence avec des supports en arbre et le dit.

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
