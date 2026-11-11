# Ligne de commande

[← Retour au README](../README.md)

Tout passe par la commande `cc2`, lancée avec uv depuis le dossier du projet (`uv run cc2 …`), ou directement après
`source .venv/bin/activate`. `cc2 --help` et `cc2 <commande> --help` donnent toutes les options.

Les commandes qui **modifient** l'imprimante (lancer, arrêter, chauffer, lumière, envoi de fichiers) demandent
`--control`, placé juste après `cc2` : `cc2 --control light on`. Sans lui, tout est en lecture seule.

## L'atelier

| Commande | Rôle |
|---|---|
| `cc2 --control dash` | l'atelier web sur http://localhost:8787/lab/ |
| `cc2 --control dash --reseau` | ouvert au téléphone et à la tablette, en HTTPS sur le port 8443 (`--port-https`, `--sans-https`) |
| `cc2 simulateur` | une CC2 simulée avec l'atelier, sur http://localhost:8788/lab/ (`--duree 120` : 2 min par impression) |
| `cc2 --control service installer` | démarrage automatique (service systemd, ouvert au réseau ; `--local` sinon) |
| `cc2 service etat` / `journal` / `retirer` | suivre ou enlever le service |
| `cc2 code-acces` | changer le code d'accès des téléphones (ils devront le ressaisir) |
| `cc2 doctor` | vérifier `config.toml`, l'imprimante et ComfyUI |

## L'imprimante

Ces commandes viennent de [pycentauri](https://github.com/bjan/pycentauri), préremplies avec l'adresse et le code de
`config.toml`.

| Commande | Rôle |
|---|---|
| `cc2 status` | l'état, une fois |
| `cc2 watch` | l'état en continu (Ctrl+C pour arrêter) |
| `cc2 attributes` | modèle, firmware, capacités |
| `cc2 canvas` | les bobines du CANVAS |
| `cc2 files` / `cc2 history` / `cc2 disk` | fichiers sur l'imprimante, historique, espace libre |
| `cc2 snapshot photo.jpg` | une photo de la caméra |
| `cc2 discover` | trouver les imprimantes du réseau |
| `cc2 --control light on` | lumière (`on` / `off`) |
| `cc2 --control upload fichier.gcode` | envoyer un fichier |
| `cc2 --control delete fichier.gcode` | supprimer un fichier de l'imprimante |
| `cc2 --control refill --on` | recharge automatique du CANVAS (`--off` pour la couper) |

## Préparer et trancher

```bash
cc2 models list                                   # la bibliothèque
cc2 models info modele.glb                        # dimensions, étanchéité, tient-il sur le plateau ?
cc2 models prepare modele.glb --height 60         # STL réparé, posé sur le plateau, à 60 mm de haut
cc2 colors modele.3mf                             # couleurs trouvées et bobine proposée pour chacune
cc2 slice modele.3mf                              # trancher (mode multicolore Économie par défaut)
cc2 slice-profiles                                # buses, qualités et filaments disponibles
```

Options de `cc2 slice` :

| Option | Rôle |
|---|---|
| `--height 80` | hauteur finale en mm |
| `--quality "0.16mm Optimal"` | profil de qualité (voir `slice-profiles`) |
| `--filament PLA --filament "PLA Silk"` | filament de chaque bobine, dans l'ordre |
| `--slot 3:1` | mettre la couleur 3 du modèle dans la bobine 1 |
| `--infill 15` | remplissage en % |
| `--supports arbre` | `aucun`, `arbre`, `arbre_fin`, `arbre_solide`, `colonnes` ; `--plateau-seul` |
| `--mode equilibre` | multicolore : `economie`, `equilibre`, `qualite`, `sans_purge` |
| `--decouper` | découper en pièces avec chevilles si trop grand |
| `--nozzle 0.6` | autre buse (tranchage simple, une couleur) |
| `--upload --start` | envoyer puis lancer (avec `cc2 --control slice …`) |

Exemples :

```bash
cc2 slice dragon.glb --height 300 --decouper --supports arbre
cc2 --control slice cube.stl --upload --start        # vérifie le plateau et le filament avant !
cc2 multicolor socle.stl:1 dessus.stl:2 --filament PLA --filament "PLA Silk"   # un fichier par couleur
```

## Génération IA

```bash
cc2 gen trellis_texte_vers_3d --prompt "un petit dragon rouge"
cc2 gen trellis_image_vers_3d --image photo.png --seed 42
```

Voir [Génération IA avec ComfyUI](comfyui.md).

## Autres

| Commande | Rôle |
|---|---|
| `cc2 server` | le serveur HTTP de pycentauri seul (l'atelier l'inclut déjà) |
| `cc2 mcp` | le serveur MCP de pycentauri (pour piloter l'imprimante depuis un assistant compatible) |
| `cc2 rtsp` | rediffuser la caméra en RTSP (H.264) avec MediaMTX |
| `make test` | les tests automatiques |
| `make deploy SERVEUR=hote` | envoyer le code sur un serveur par ssh et y relancer l'atelier |
