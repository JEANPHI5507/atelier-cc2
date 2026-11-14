# Suivre une impression

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/monitoring.md)

## L'onglet Imprimante

- **Impression** : nom, état, progression, couche, temps restant, heure de fin ; pause, reprise, arrêt (avec
  confirmation). Au repos : « Mettre au repos » coupe chauffes, ventilateurs et lumière.
- **Couleur en cours et à venir** : la bobine vraiment engagée dans le CANVAS, puis les prochains changements avec leur
  couche et le délai estimé (« Silk Or · couche 81 · dans 2 min »), et le nombre de changements restants. Quand une
  couche contient plusieurs changements, la bobine engagée dit où en est l'impression dans la couche. En dessous, les
  **purges restantes par couleur** (« Silk Or 23 / 24 ») : combien de fois chaque bobine passera encore par la goulotte.
- **Caméra** en direct, image par image (toujours la plus récente, même sur une connexion lente), avec la lumière.
- **Couche par couche** : la pièce en 3D, en couleur ce qui est imprimé, en gris ce qui reste ; elle avance toute seule.
- **Températures** (buse, plateau, caisson) avec des préréglages PLA, PETG, ABS et « Refroidir ».
- **Position de la buse** : X, Y, Z en mm, chaque seconde, et le plateau vu de dessus avec les derniers déplacements ;
  « À la goulotte » quand elle va purger à un changement de couleur. Quand la vue « Couche par couche » est là, tout
  s'affiche dessus, et un cône orange montre la buse sur la pièce.
- **Bobines CANVAS** : couleur, matière, grammes restants, recharge automatique. Cliquer une bobine corrige son poids,
  le poids d'une bobine pleine et son prix au kilo.
- **Fichiers sur l'imprimante** et **Historique** (repliés) ; « Interface avancée » ouvre l'interface de pycentauri.

Le suivi couche par couche et les couleurs à venir ont besoin du G-code dans la bibliothèque : une impression lancée
depuis l'écran de la CC2, avec un fichier venu d'ailleurs, n'a que la caméra et la progression.

## La caméra et l'IA anti-ratés

Pendant l'impression, une image toutes les 10 secondes passe dans le modèle libre d'**Obico** (The Spaghetti
Detective, AGPL-3.0), **sur la machine de l'atelier** : aucune image ne sort de la maison. Il compare chaque image à la
« normale » de cette impression et attend 30 images (5 minutes) avant de juger.

- Un doute : alerte « Impression suspecte » avec la photo encadrée.
- Une certitude : « Raté détecté », et **pause automatique** si tu l'as activée.
- Après une reprise, l'IA repart de zéro. Elle s'arrête à 98 % : les derniers mouvements et les détails fins d'une
  pièce finie ressemblent trop à des spaghettis.
- Réglages (carte « Surveillance par caméra ») : IA, pause automatique, sensibilité, timelapse. Le modèle (200 Mo)
  s'installe d'un clic ou avec `make ia`.

La caméra est aussi surveillée elle-même : une image figée (défaut connu de certains firmwares, réglé par un arrêt
complet de l'imprimante) est signalée, et l'IA et le timelapse se mettent en pause au lieu de juger une image figée.

## Timelapse et galerie

Une photo à chaque nouvelle couche, assemblée en vidéo à la fin (il faut `ffmpeg`). L'onglet **Galerie** garde chaque
impression : vidéo, photo de fin, durée, grammes, coût, issue (terminée, arrêtée, erreur) et les alertes de l'IA avec
leurs photos. **Réimprimer** relance le même G-code, avec la vérification des bobines. Les 200 dernières sont gardées.

## Le bilan

Après une impression (bouton **Bilan** dans la galerie, ou **Faire le bilan** dans la notification de fin) :

1. L'atelier rappelle quoi faire maintenant, selon la pièce : attendre que le plateau refroidisse, retirer les
   supports, vider le bac de purge après du multicolore, ne pas poncer le PLA Silk…
2. Tu coches ce qui n'allait pas : pièce décollée, fils, dessus troué, couture visible, pièce fragile, supports durs à
   enlever, surplombs affaissés, lignes maigres, couleurs qui bavent, gouttes aux changements, tour de purge tombée,
   pied d'éléphant, couches décalées.
3. Pour chaque défaut : la cause probable, le geste à faire sur cette pièce, et la correction pour la prochaine fois,
   calculée sur les vrais réglages de l'impression (une buse à 230 °C qui file passe à 220 °C, pas « 10 °C de moins
   que le profil »).

Les corrections sont gardées sur le modèle : la prochaine fois que tu le prépares, l'atelier les propose en un clic.

## Le plateau froid

Après une fin d'impression, l'atelier attend que le plateau descende sous 35 °C : à cette température, une pièce en
PLA se décolle presque seule du PEI. Il prévient alors (« Plateau froid : tu peux retirer la pièce »), sur la page et
sur le téléphone. Si le plateau ne refroidit pas en 3 heures, il abandonne.

## Bobines et coûts

Chaque bobine du CANVAS a un stock (1 kg et 20 €/kg par défaut, modifiables). Au tranchage : grammes et coût par
bobine, purge comprise. À la fin d'une impression (ou à l'arrêt, au prorata), le filament est retiré des bonnes bobines ;
« bobine presque vide » sous 100 g. Une bobine retirée du CANVAS garde ce qu'il lui reste : remise plus tard, dans
n'importe quel tiroir, elle reprend ce poids (alerte « Bobine remise »). Une bobine jamais vue (autre puce, couleur ou
matière) repart pleine. Dans les deux cas, l'onglet Imprimante (et la tablette) demande de confirmer : « La même » ou
« Une neuve » pour une bobine reconnue, « Neuve » ou « Déjà entamée… » (le poids restant) pour une inconnue. Le total du mois est affiché sous les bobines.

## Le carnet d'entretien

Dans l'onglet Imprimante, d'après les heures réelles d'impression et le calendrier : laver le plateau PEI (30 h),
l'essuyeur et la goulotte (50 h), tiges et courroies (250 h ou 90 jours), filtre (90 jours), coupe-filament et aimants
du capot (150 h). Une alerte prévient quand une tâche arrive à échéance ; « Fait » la remet à zéro.
