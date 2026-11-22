---
name: cc2-orcaslicer
description: OrcaSlicer piloté par l'atelier pour la Centauri Carbon 2 — binaire, profils Elegoo (machine/qualité/filament), températures automatiques, réglages fins disponibles dans l'outil trancher. Charge-la dès qu'il faut trancher, choisir une qualité, ajuster remplissage, parois, couture, température et raisonner dessus.
user-invocable: false
---

# OrcaSlicer — le tranchage de l'Atelier CC2

## Le principe

L'atelier lance OrcaSlicer en ligne de commande (le binaire vit sous `tools/orcaslicer/` de l'atelier,
`make slicer` le télécharge ; `[slicer] path` dans config.toml sinon). Tu NE lances JAMAIS Orca à la main :
l'outil `trancher` fait tout, avec les bons profils verrouillés dessus.

## Les profils (ce que l'atelier verrouille pour toi)

- MACHINE : `Elegoo Centauri Carbon 2 <0.2|0.4|0.6|0.8> nozzle` — la vraie machine : plateau texte PEI 256×256,
  Z 256, buse 0,4 par défaut. La buse suit toujours le profil machine.
- QUALITÉ (hauteur de couche) — buse 0.4 : « 0.12mm Fine », « 0.16mm Optimal », « 0.20mm Standard »,
  « 0.20mm Strength », « 0.24mm Draft », « 0.28mm Extra Draft ». Chaque usage de l'atelier en choisit une
  par défaut : decoratif→0.20 Standard, fonctionnel→0.20 Strength, detaille→0.12 Fine, rapide→0.24 Draft.
  Change seulement si l'utilisateur le demande, ou pour une pièce qui l'exige (relief fin → Fine).
- FILAMENT : le CANVAS porte 4 bobines ; le profil filament de chaque bobine vient d'Elegoo (ou du catalogue
  utilisateur construit dessus). LA CLÉ : températures buse et plateau se RÈGLENT SEULES d'après le filament
  de la bobine — ne fixe temp_buse/temp_plateau que si l'utilisateur le demande explicitement ou si le
  filament l'exige (ABS : plateau 90-100, buse 250+ ; PETG : 75-80 plateau).

## Les réglages fins que l'outil `trancher` te laisse ajuster (clés françaises, validées)

| Clé | Effet | Valeurs utiles |
|---|---|---|
| parois | périmètres | 3 standard, 4-5 fonctionnel |
| dessus / dessus couches | coquilles | plus = plus étanche (2 = min) |
| motif | remplissage | gyroîde (fonctionnel), nid_abeille, cubique, eclair (déco), grille |
| couches | épaisseur variable | auto/pentes/rapide/non (les fines sur les pentes lissent les dômes) |
| lissage | ironing | dessus, dernier, non |
| couture | seam | le plus discret : proche ; arrière sur les cylindres visibles |
| peau | bave | exterieur (anti-corrosion du détail) |
| bordure | brim | exterieure (pièce fine), oreilles |
| ordre | ordre d'impression d'un plateau | suite = pièce par pièce, couleurs regroupées (béaucoup moins de changements ; il faut 65 mm entre pièces et 36 mm de haut, l'atelier refuse sinon) ; couche par défaut |
| angle_support | seuil de surplomb | 45 (par défaut), 55 plus sûr, 60 rapide |
| radeau | raft | 0-1 par défaut |
| temp_buse / temp_plateau | voir ci-dessus (auto sinon) | PLA buse 220 par défaut |
| avance_pression / debit | calibration filament | tour de calibration uniquement |

Toujours annoncé : « durée X h, Y g, bobine Cin N » (le G-code de l'outil porte les températures du profil).

## Pièges connus (l'atelier les gère, mais tu dois les expliquer)

- Remplissage 100 % sans raison : double le temps pour rien — gyroid ou cubique à 25-40 % fait le même
  travail fonctionnel.
- Sans supports, Orca refuse (code -100) une pièce qui flotterait : l'atelier relance automatiquement
  en arbre et le dit — tu le signales avant le tranchage quand l'analyse du modèle le montre.
- « ramming » multimatière : verrouillé OFF (la CC2 s'arrête en erreur 1243 sinon) — ne le touche pas.
- La purge entre deux couleurs : plus le CANVAS change souvent de couleur, plus la purge gâche —
  si l'utilisateur vise l'économie, propose de simplifier les couleurs (moins de changements et de purge).
- Une pièce envoyée trop tôt s'arrache par morceaux : la CC2 termine par un refroidissement, attends sa
  fin avant d'annoncer le prêt (le suivi de l'app gère l'alerte).
