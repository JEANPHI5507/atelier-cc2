# Développement

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/development.md)

## Organisation

```
src/elegoo_lab/
  cli.py            la commande cc2 (reprend celles de pycentauri, préremplies)
  app.py            le serveur web (FastAPI) : routes /lab/api/…, monté sur le serveur de pycentauri
  web/              l'interface, sans étape de build
    index.html        structure de l'atelier ; css/app.css (thèmes, mobile)
    js/core.js        outils communs ; lab.js (atelier, 3D, tranchage) ; printer.js (onglet Imprimante)
    js/gallery.js, alerts.js, setup.js (Démarrage), app.js (onglets, démarrage)
    tableau.html + js/tableau.js   la tablette (JavaScript ancien, sans modules : vieux navigateurs)
    vendor/           three.js ; cc2/ (plateau copié depuis OrcaSlicer par make plateau)
  slicer.py         OrcaSlicer en ligne de commande, profils CC2, purge M6211
  printprep.py      du modèle au G-code : couleurs, taille, pose, modes multicolores, découpe, exemplaires
  colors.py         couleurs d'un modèle, conversion pour le CANVAS, purge dosée, simplification
  colorize.py       assemblage de pièces en un 3MF multicolore
  mesh.py, orient.py, cut.py, advisor.py, optimize.py   maillage, positions, découpe, conseiller, « Optimiser »
  parametric.py, parametric_more.py, addtext.py          les pièces de « Créer »
  forme.py          percer ou ajouter une forme ; couches.py (hauteur de couche variable)
  launch.py         lancement (table bobines, options machine) ; spools.py, stock.py (bobines, coûts)
  alerts.py         le suivi permanent de l'imprimante et les alertes ; vision.py (IA caméra) ; gallery.py
  camfeed.py        la caméra image par image ; coupe.py, suivi_couleurs.py (tablette, couleurs à venir)
  aftercare.py      le bilan ; maintenance.py (entretien) ; bedcheck.py (plateau vide)
  access.py, certs.py   code d'accès, HTTPS, Tailscale
  comfy.py          client ComfyUI ; simulateur.py (la CC2 simulée)
  library.py, importlink.py, thumbnail.py, threemf.py, repair.py   bibliothèque, import par lien, vignettes, 3MF, réparation
  catalog.py, settings.py, calibration.py, gcode_preview.py         profils, réglages avancés, tours de test, aperçu des trajets
  connexion.py, errors.py   onglet Démarrage (test de connexion) ; codes d'erreur de la CC2
  config.py         config.toml
workflows/          workflows ComfyUI (format API) et leur .map.json
tests/              test_core.py (serveur), test_ui.py (un vrai Chrome clique dans l'atelier), conftest.py
docs/               la page d'accueil (GitHub Pages) et ses images
guide/              ces guides (français), guide/en/ (anglais)
```

## Lancer en développement

```bash
uv sync                                  # avec les outils de test
uv run cc2 simulateur --duree 60         # l'atelier sur une CC2 simulée : http://localhost:8788/lab/
```

L'interface est en fichiers statiques relus à chaque ouverture : modifier un `.js` ou un `.css` ne demande qu'un
rechargement de la page. Une modification Python demande de relancer la commande.

Pour vérifier un module JavaScript sans navigateur : `node --input-type=module --check < src/elegoo_lab/web/js/lab.js`
(la tablette : `node --check src/elegoo_lab/web/js/tableau.js`).

## Les tests

```bash
make test                # ou : uv run pytest -q
```

- `tests/test_core.py` : le serveur, le tranchage, les couleurs, les alertes, la caméra… avec la CC2 simulée.
  Certains tests tranchent vraiment avec OrcaSlicer (il faut `make slicer`).
- `tests/test_ui.py` : un vrai Chrome (Playwright) clique dans un atelier de test, avec sa propre bibliothèque et ses
  ports ; ignoré si Chrome n'est pas installé (`uv run playwright install chromium`).

## Le simulateur

`src/elegoo_lab/simulateur.py` est un petit broker MQTT 3.1.1 et une fausse CC2 qui parlent le protocole documenté par
pycentauri : état, CANVAS de quatre bobines, fichiers, impressions en accéléré, caméra dessinée, envoi de fichiers.
Ce n'est pas un modèle fidèle du firmware : ce qui est vrai sur la vraie imprimante est noté dans
[Ce qu'il faut savoir sur la CC2](cc2.md).

## Conventions

- Textes de l'interface en français, au tutoiement, concrets (ce qui se passe et quoi faire), sans jargon.
- Les commentaires disent pourquoi, pas quoi.
- pycentauri est figé en 0.9.1 : protocole issu de la rétro-ingénierie, à mettre à jour volontairement seulement.
- Toute action qui modifie l'imprimante passe par `--control` ; toute requête qui modifie quelque chose est refusée si
  elle vient d'un autre site que l'atelier.
