# Installation

[← Retour au README](../README.md)

L'atelier est un serveur web écrit en Python. Il tourne sur une machine **Linux x86-64** de la maison, reliée au même
réseau que l'imprimante, et on l'ouvre dans un navigateur : sur cette machine, sur un téléphone ou sur une tablette.
La machine doit rester allumée pendant les impressions pour suivre la caméra et envoyer les alertes (l'impression,
elle, continue même si l'atelier s'arrête : elle tourne sur la CC2).

## Ce qu'il faut

| | Minimum | Confortable |
|---|---|---|
| Système | Linux x86-64 (Ubuntu 24.04 ou plus récent testé) | |
| Processeur | 2 cœurs | 4 cœurs ou plus : le tranchage va plus vite |
| Mémoire | 4 Go | 8 Go |
| Disque | 3 Go (atelier + OrcaSlicer + modèle IA) | plus pour ta bibliothèque et les timelapses |
| Réseau | même réseau local que l'imprimante | |

Ordre de grandeur mesuré : le tranchage d'une figurine de 60 mm en quatre couleurs (300 couches) prend 5 s sur un
mini-PC récent et 17 s sur un i5 de 2015. L'IA de la caméra analyse une image en 0,1 à 0,2 s, une fois toutes les 10 s.

Logiciels :

- **Python 3.12** et **[uv](https://docs.astral.sh/uv/)** (gestionnaire de paquets Python). Si ton système a une autre
  version de Python, uv installe la bonne à part : `uv python install 3.12`.
- **git**, **make**, **curl** (souvent déjà là).
- **ffmpeg** pour assembler les timelapses en vidéo : `sudo apt install ffmpeg`. Sans lui, les photos de chaque couche
  sont gardées, mais pas la vidéo.

## Installer

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2
cd atelier-cc2
uv sync                 # crée .venv/ avec toutes les dépendances
make slicer             # télécharge OrcaSlicer 2.4.2, vérifie son empreinte SHA-256, l'extrait dans tools/
make ia                 # facultatif : le modèle anti-ratés d'Obico (≈ 200 Mo), vérifié lui aussi
```

`make slicer` copie aussi le modèle 3D et le marquage du plateau de la CC2 fournis avec OrcaSlicer
(`make plateau` le refait seul). Sans eux, la vue 3D garde un plateau uni.

Le modèle IA peut aussi s'installer plus tard, d'un clic, depuis l'onglet Imprimante (carte « Surveillance par caméra »).

### Sur un serveur sans écran

OrcaSlicer charge des bibliothèques graphiques même quand il tranche en ligne de commande. Sur un serveur sans
interface graphique, installe-les (Ubuntu / Debian) :

```bash
sudo apt update
sudo apt install -y libatk1.0-0t64 libcairo2 libcairo-gobject2 libegl1 libfontconfig1 libgdk-pixbuf-2.0-0 libgl1 \
  libglu1-mesa libglx0 libgstreamer-plugins-base1.0-0 libgtk-3-0t64 libharfbuzz0b libice6 libjavascriptcoregtk-4.1-0 \
  libopengl0 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 libsecret-1-0 libsm6 libsoup-3.0-0 \
  libwayland-client0 libwayland-egl1 libwayland-server0 libwebkit2gtk-4.1-0
```

Pour savoir s'il en manque : `ldd tools/orcaslicer/squashfs-root/bin/orca-slicer | grep "not found"`. Si un tranchage
échoue avec « missing host OpenGL runtime library », c'est ce point.

## Premier lancement

```bash
uv run cc2 --control dash
```

Ouvre http://localhost:8787/lab/ sur la machine. L'onglet **Démarrage** guide la connexion à l'imprimante : voir
[Première connexion](premiere-connexion.md). Les réglages sont écrits dans `config.toml` (ignoré par git, lisible par
toi seul) ; tu peux aussi partir de `config.example.toml`.

- Sans `--control`, l'atelier est en **lecture seule** : il montre tout, mais ne lance, n'arrête ni ne chauffe rien.
- Par défaut il n'écoute que la machine elle-même (`127.0.0.1`). Pour l'ouvrir au téléphone et à la tablette, ajoute
  `--reseau` : voir [Téléphone, tablette, hors de la maison](telephone-et-tablette.md).

Tu peux d'abord tout essayer sans imprimante avec `uv run cc2 simulateur` (http://localhost:8788/lab/).

## Démarrage automatique

```bash
uv run cc2 --control service installer
```

L'atelier devient un service systemd de ton utilisateur : il démarre avec la machine, même sans session ouverte, et se
relance tout seul s'il s'arrête. Il est ouvert au réseau (`--reseau`) par défaut ; `--local` le garde sur la machine.

```bash
uv run cc2 service etat       # tourne-t-il ?
uv run cc2 service journal    # ses derniers messages
uv run cc2 service retirer    # l'enlever
```

Ne lance plus `cc2 dash` à la main en même temps : les ports seraient déjà pris. Si le service ne démarre pas sans
session ouverte, active le « linger » une fois : `sudo loginctl enable-linger $USER`.

## Mettre à jour

```bash
cd atelier-cc2
git pull
uv sync
make slicer                     # sans effet si OrcaSlicer est déjà à la bonne version
uv run cc2 service etat         # puis : systemctl --user restart cc2-atelier
```

Ta bibliothèque (`models/`), `config.toml` et les certificats (`.certs/`) ne sont jamais touchés par une mise à jour.
Le téléphone et la tablette affichent la nouvelle interface dès leur prochaine ouverture.

Pendant une impression, redémarrer l'atelier est sans danger pour l'impression : l'atelier reprend son suivi en
cours de route (l'IA de la caméra repart de zéro et rejuge au bout de 5 minutes).

## Installer sur un serveur et coder ailleurs

Si l'atelier tourne sur un serveur de la maison et que tu modifies le code sur un autre PC, `make deploy` envoie le
code par ssh et relance le service :

```bash
make deploy SERVEUR=mon-serveur     # « mon-serveur » : un hôte de ton ~/.ssh/config ; dossier ~/elegoo sur le serveur
```

Il n'envoie que le code (`src/`, `pyproject.toml`, `uv.lock`…) : la bibliothèque, `config.toml`, `.certs/` et `tools/`
du serveur restent les siens.

## Déménager l'atelier sur une autre machine

Tout tient dans le dossier du projet. Pour garder ton historique, copie en plus du code :

- `models/` : bibliothèque, galerie, bobines, alertes, file d'attente, bilans ;
- `config.toml` : imprimante, code d'accès, alertes ;
- `.certs/` : l'autorité de certification que tes téléphones connaissent déjà (sans elle, il faudra réinstaller le
  certificat sur chaque appareil).

Arrête l'atelier sur l'ancienne machine avant de copier, puis installe le service sur la nouvelle.
