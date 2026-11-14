# Ce qu'il faut savoir sur la CC2

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/cc2.md)

Ce que l'atelier a appris de la Centauri Carbon 2, et dont il tient compte. Sources : le **code source officiel du
firmware** ([elegooofficial/CentauriCarbon2](https://github.com/elegooofficial/CentauriCarbon2), GPL-3.0 : codes
d'erreur, CANVAS, macro `M6211`), les essais sur une vraie CC2 (firmware 02.01.01.13), puis les retours de
propriétaires et les journaux de version ([OpenCentauri](https://docs.opencentauri.cc/software/updates-cc2/),
[printer-hub.com](https://printer-hub.com/posts/elegoo-centauri-carbon-2-known-issues),
[printer-protocol-orchard](https://github.com/ChestnutLabs/printer-protocol-orchard/blob/main/protocols/elegoo.md)).

Le dépôt du firmware ne contient pas la couche réseau : les commandes du protocole viennent de
[pycentauri](https://github.com/bjan/pycentauri) et ne sont pas confirmées par Elegoo.

## Réseau local

- Le mode **« LAN Only »** est nécessaire. Il coupe l'IA et la vidéo d'Elegoo dans le cloud, que l'atelier remplace.
- L'imprimante parle en **MQTT sur le port 1883** (état, commandes) et sert sa **caméra en MJPEG sur le port 8080**,
  ouverte à tout le réseau local.
- **Refusé sur le réseau local** (SDK d'Elegoo) : mise en origine, déplacements, décalage Z, calibrations, chargement
  de filament. La consigne de température est refusée elle aussi (erreur 1003). Ça se fait sur l'écran ; l'atelier le
  dit quand il ne peut pas.
- Une impression terminée passe de ~97 % à « prête » sans état « terminée » : l'atelier lit l'historique de
  l'imprimante pour savoir si elle a fini ou été arrêtée.
- Pendant une **mise à jour du firmware**, l'imprimante annonce un état à part (9), puis se déconnecte environ une
  minute : l'atelier ne le prend pas pour une impression.

## CANVAS et changements de couleur

- Un changement de couleur, dans le G-code, est la macro **`M6211 T<n> L<mm de purge>`** (pas un simple `T<n>`).
- La purge se fait dans la **goulotte à l'arrière** (X52, Y264). Le firmware pousse **toujours au moins 23 mm + 6 mm**
  de filament par changement, même si le slicer en demande moins : réduire encore la matrice de purge ne sert à rien.
  OrcaSlicer sous-estime donc la purge ; l'atelier la recompte comme le firmware.
- La macro d'Elegoo purge à **240 °C** puis l'impression reprend à sa température : la buse revient très fluide. Avec
  une tour d'essuyage, le fil fait des boucles dessus ; l'atelier lève la buse de 0,8 mm et élargit la base de la tour.
- Les bobines du CANVAS sont numérotées 0 à 3 en interne ; un canal est libre (0), préchargé (1) ou chargé (2).
- Sans table de correspondance envoyée au lancement, la CC2 imprime T0 avec la bobine 1, T1 avec la 2, etc.
  L'atelier envoie toujours la table choisie dans la fenêtre de lancement.
- Le **bac de purge** se remplit vite en multicolore : l'atelier le rappelle après chaque impression multicolore.

## Tranchage

- La CC2 refuse un G-code dont les profils de filament ne portent pas ses noms : l'atelier remet les noms officiels
  (« Elegoo PLA @ECC2 »).
- **Ramming désactivé**, comme dans ElegooSlicer : activé, il provoque l'erreur 1243 (extrusion anormale).
- La CC2 **nivelle toujours** avant d'imprimer. L'atelier garde le maillage de nivellement du slicer (limité à la zone
  de la pièce, plus rapide) ; le retirer (`[tranchage] niveler = false`) la fait niveler tout le plateau. Sur une
  petite pièce, elle ne palpe que sa zone (16 points, une étoile de 28 mm) ; sur une grande zone qui touche le bord du
  plateau (tour de purge comprise), elle a déjà palpé tout le plateau (environ 9 min). Ce choix est fait par un module
  fermé d'Elegoo.
- Le firmware lit `EXCLUDE_OBJECT_DEFINE` comme Klipper : avec plusieurs exemplaires, on peut abandonner une pièce
  ratée et finir les autres.
- `PAUSE` dans le G-code marche : la tête se gare au-dessus du bac et la buse baisse à 100 °C.
- `SET_PRESSURE_ADVANCE` et `M221` (débit) sont acceptés : ce sont les réglages « avance de pression » et « débit »
  des réglages avancés.
- Coin interdit du plateau : 246-256 × 0-20 mm (avant droit). L'atelier n'y pose rien.

## Erreurs et défauts connus

- Les **34 codes d'erreur** de la liste officielle du firmware sont expliqués dans les alertes avec le geste à faire :
  chauffe, capteurs, ventilateurs, 704 nivellement, 707 capot de la tête décroché, 801-803 liaisons, 1101/1103 grille
  d'extraction, 1210-1264 CANVAS (bobine vide, coupe-filament, chargement, retrait, filament emmêlé).
- **Caméra figée** (firmware ≥ 01.03.01.89) : elle revient après un arrêt complet. L'atelier la détecte, le signale,
  et met l'IA et le timelapse en pause. Il allume la lumière au départ : lumière éteinte, la caméra est noire.
- **Matières** : TPU (pas par le CANVAS, pas de nivellement à 60 °C), filaments abrasifs (ils usent le capteur du
  CANVAS), matières haute température (chargement à 250 °C), ABS/ASA (caisson passif, 35 à 45 °C) : l'atelier prévient
  au lancement.

## Firmware

Ne mets à jour que pour corriger un problème : depuis 02.00.02.00, le retour en arrière est bloqué, et une mise à jour
peut changer le protocole réseau dont dépend l'atelier.
