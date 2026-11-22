---
name: cc2-impression3d
description: Le métier de l'impression FDM pour l'Atelier CC2 (Elegoo Centauri Carbon 2) : orientation, supports, tolérances, parois, couches, adhérence, températures, usages. Charge-la dès qu'une question ou une action touche la fabrication — « ça tiendra ? », poser, percer, supports, trancher.
user-invocable: false
---

# Métier impression 3D — Centauri Carbon 2

La machine : plateau 256×256 mm, Z 256 mm, buse 0,4 mm, profils Elegoo intégrés à l'atelier, CANVAS 4 bobines (les températures se règlent d'après le filament de chaque bobine — ne donne jamais une température à la main).

## Orientation (à traiter AVANT tout le reste)

- Surplombs au-delà de ~45° : chaque couche dépasse alors dans le vide, le plastique file en bavure ou fond en paquet. Tourner la pièce vaut toujours mieux qu'un support.
- Contact plaque : la plus grande face plate au sol, arêtes « brute de couche » cachées dessous ou sur la face arrière.
- Pas besoin de support dans un surplomb qui finit dans la pièce ou près du plateau.
- L'outil `orienter` donne les poses classées par surplomb : appelle-le au lieu de deviner.

## Supports

- `arbre` : par défaut — touche peu, s'arrache, cicatrices légères.
- `arbre_fin` : pièces légères ou de décoration, le plus économique.
- `arbre_solide` : pièces lourdes, hautes ou chargées (buste, boîtier plein).
- `colonnes` : grands plafonds plats (à l'intérieur d'une boîte par exemple).
- Les zones peintes « jamais de support » et « support ici » à la main dans la vue 3D gagnent toujours sur le réglage global.

## Tolérances fonctionnelles (à annoncer, jamais improvisées)

- Jeu d'assemblage : ~0,2 mm par côté entre deux pièces qui s'emboîtent.
- Trou de vis : passe au diamètre de vis + 0,1–0,2 mm (M3 → 3,2–3,4 mm).
- Trou d'aimant : diamètre d'aimant + 0,2 mm, profondeur d'aimant + 0,4 mm, percé en travers du plus petit côté ; si la pièce est assez haute, une PAUSE au bon niveau (champ « Pause à la hauteur ») permet d'encastrer l'aimant en cours d'impression.
- Parois jamais sous ~0,8 mm (4 périmètres conseillés pour du fonctionnel), piliers fins à épaisir, pics à adoucir.

## Couches et détails

- Hauteur de couche 0,2 mm standard : une gravure lisible demande ~1 mm de profondeur OU des bords nets ; plus fin, il disparaît.
- Ponts courts OK (jusqu'à ~20 mm), au-delà : supports.
- Trous horizontaux resserrés par la couche du dessus → prévois -0,15 mm ou perce après impression.

## Adhérence

- Petit contact plaque → bordure (brim). Grande surface → rien.
- Pièces avec pointes isolées : oriente la pointe vers le haut ou coupe en deux.
- Ne jamais laisser une pièce « flottante » passer le tranchage : l'atelier relance avec des supports d'arbre tout seul.

## Usages de l'atelier (le tranchage en déduit tout le reste)

| Usage | Quand |
|---|---|
| decoratif | la pièce sera regardée, pas forcée |
| fonctionnel | vis, emboîtement, charnière : solide |
| detaille | gravures, petits reliefs, visages |
| rapide | brouillon de forme avant le vrai tirage |
| turbo | très rapide, grosses couches, prévisualisation |

Réponds toujours avec ces réalités chiffrées en tête : quand une demande exige un compromis (support ↔ cicatrice, jeu ↔ tenue), dis-le en une phrase et choisis, au lieu de demander.
