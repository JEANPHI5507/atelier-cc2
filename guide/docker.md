# Guide d'Installation Docker

[\u2190 Retour au README](../README.fr.md) \u00b7 \ud83c\uddec\ud83c\udde7 [English](en/docker.md)

## Présentation

Ce guide explique comment exécuter **Atelier CC2** avec Docker. C'est la méthode recommandée pour :
- **Les utilisateurs Windows** (via WSL2)
- **Les utilisateurs macOS** (via Docker Desktop)
- **Les utilisateurs Linux** qui veulent un environnement isolé
- **Les déploiements sur serveur**

## Prérequis

- [Docker](https://docs.docker.com/get-docker/) installé
- [Docker Compose](https://docs.docker.com/compose/install/) (optionnel, pour les configurations multi-conteneurs)
- **4 Go de RAM minimum** (recommandé : 8 Go pour toutes les fonctionnalités)
- **2 Go d'espace disque** (pour OrcaSlicer et les dépendances)

## Démarrage Rapide

### 1. Cloner le Dépôt

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
```

### 2. Construire l'Image Docker

```bash
# Construire l'image (prend ~5-10 minutes)
docker build -t atelier-cc2 .
```

### 3. Exécuter avec le Simulateur (Pas d'Imprimante Requise)

```bash
# Exécuter le simulateur (mode démo)
docker run -it --rm \
  -p 8788:8788 \
  -v $(pwd)/demo:/home/appuser/app/demo \
  atelier-cc2
```

Ouvrez ensuite votre navigateur à l'adresse : **http://localhost:8788/lab/**

### 4. Exécuter avec une Vraie Imprimante CC2

```bash
# Exécuter avec votre CC2 (remplacez IP et CODE par les valeurs de votre imprimante)
docker run -it --rm \
  -p 8787:8787 \
  -v $(pwd)/config.toml:/home/appuser/app/config.toml:ro \
  -v $(pwd)/models:/home/appuser/app/models \
  -v $(pwd)/demo:/home/appuser/app/demo \
  atelier-cc2 \
  --control dash --ip 192.168.1.100 --code 123456
```

Ouvrez ensuite votre navigateur à l'adresse : **http://localhost:8787/lab/**

## Utilisation de Docker Compose

### 1. Démarrer le Simulateur

```bash
# Démarrer avec le simulateur
docker-compose up -d

# Voir les logs
docker-compose logs -f atelier-cc2

# Arrêter
docker-compose down
```

Accédez à l'interface à l'adresse : **http://localhost:8788/lab/**

### 2. Configurer pour une Vraie Imprimante

Éditez le fichier `docker-compose.yml` et mettez à jour la commande :

```yaml
services:
  atelier-cc2:
    # ... autres configurations ...
    command: ["--control", "dash", "--ip", "VOTRE_IP_IMPRIMANTE", "--code", "VOTRE_CODE_ACCES"]
```

Puis redémarrez :

```bash
docker-compose down && docker-compose up -d
```

## Persistance des Données

Les répertoires suivants sont persistés par défaut :

| Répertoire Local | Chemin dans le Conteneur | Utilisation |
|-------------------|--------------------------|-------------|
| `./config.toml` | `/home/appuser/app/config.toml` | Fichier de configuration |
| `./models` | `/home/appuser/app/models` | Bibliothèque de modèles 3D |
| `./demo` | `/home/appuser/app/demo` | Données du simulateur |
| `./gallery` | `/home/appuser/app/gallery` | Historique des impressions et photos |

## Installation d'OrcaSlicer

OrcaSlicer est installé automatiquement au premier démarrage. Cependant, vous pouvez aussi l'installer manuellement :

```bash
# Entrer dans le conteneur
docker run -it --rm \
  -v $(pwd):/home/appuser/app \
  atelier-cc2 bash

# Dans le conteneur, exécutez :
cd /home/appuser/app
make slicer
```

## Installation du Modèle IA (Optionnel)

Pour activer la détection de "spaghetti" par IA :

```bash
# Entrer dans le conteneur
docker run -it --rm \
  -v $(pwd):/home/appuser/app \
  atelier-cc2 bash

# Dans le conteneur, exécutez :
cd /home/appuser/app
make ia
```

## Variables d'Environnement

| Variable | Description | Valeur par Défaut |
|----------|-------------|-------------------|
| `PYTHONUNBUFFERED` | Désactive la mise en mémoire tampon de la sortie Python | `1` |
| `PYTHONDONTWRITEBYTECODE` | Désactive l'écriture des bytecodes Python | `1` |

## Ports

| Port | Service | Description |
|------|---------|-------------|
| 8787 | Atelier CC2 (Mode Contrôle) | Avec une vraie imprimante |
| 8788 | Atelier CC2 (Mode Simulateur) | Mode démo |

## Résolution des Problèmes

### Erreurs "Permission Denied"

Assurez-vous que les répertoires locaux existent et ont les bonnes permissions :

```bash
mkdir -p models demo gallery
chmod -R 777 models demo gallery
```

### Échec de la Construction Docker

Essayez de nettoyer le cache Docker :

```bash
docker system prune -a
docker build --no-cache -t atelier-cc2 .
```

### OrcaSlicer Non Trouvé

Assurez-vous qu'OrcaSlicer est installé :

```bash
docker run -it --rm atelier-cc2 make slicer
```

### Port Déjà Utilisé

Vérifiez quel processus utilise le port :

```bash
# Sur Linux
sudo lsof -i :8788

# Sur Windows
netstat -ano | findstr 8788
```

Puis soit arrêtez le processus conflictuel, soit utilisez un autre port en modifiant la commande `docker run`.

## Spécificités Windows (WSL2)

### 1. Installer WSL2

```powershell
# Activer WSL
wsl --install

# Définir WSL2 comme version par défaut
wsl --set-default-version 2
```

### 2. Installer Docker Desktop

Téléchargez et installez [Docker Desktop pour Windows](https://docs.docker.com/docker-for-windows/install/)

### 3. Activer l'Intégration WSL2

1. Ouvrez Docker Desktop
2. Allez dans **Paramètres > Ressources > Intégration WSL**
3. Activez l'intégration avec votre distribution WSL2

### 4. Exécuter Atelier CC2

```bash
# Dans le terminal WSL2
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
docker build -t atelier-cc2 .
docker run -it --rm -p 8788:8788 atelier-cc2
```

## Spécificités macOS

### 1. Installer Docker Desktop

Téléchargez et installez [Docker Desktop pour Mac](https://docs.docker.com/docker-for-mac/install/)

### 2. Augmenter les Ressources Docker

1. Ouvrez Docker Desktop
2. Allez dans **Préférences > Ressources**
3. Augmentez la mémoire à au moins **4 Go** (recommandé : 8 Go)
4. Augmentez l'espace disque à au moins **20 Go**

### 3. Exécuter Atelier CC2

```bash
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2
docker build -t atelier-cc2 .
docker run -it --rm -p 8788:8788 atelier-cc2
```

## Conseils de Performance

1. **Utilisez le cache Docker** : La première construction prend plus de temps, mais les constructions suivantes sont plus rapides.
2. **Limitez les threads d'OrcaSlicer** : Si vous avez un CPU limité, vous pouvez limiter les threads d'OrcaSlicer :
   ```bash
   docker run -it --rm -e OMP_NUM_THREADS=2 atelier-cc2
   ```
3. **Utilisez un volume séparé pour OrcaSlicer** : Pour éviter de reconstruire OrcaSlicer :
   ```bash
   docker run -it --rm \
     -v orcaslicer_cache:/home/appuser/app/OrcaSlicer \
     atelier-cc2
   ```

## Mise à Jour

Pour mettre à jour vers la dernière version :

```bash
# Récupérer les dernières modifications
git pull origin main

# Reconstruire l'image
docker build -t atelier-cc2 . --no-cache

# Redémarrer le conteneur
docker-compose down && docker-compose up -d
```

## Désinstallation

Pour supprimer complètement Atelier CC2 :

```bash
# Arrêter et supprimer les conteneurs
docker-compose down

# Supprimer l'image
docker rmi atelier-cc2

# Supprimer les volumes (ATTENTION : Cela supprimera toutes vos données !)
docker volume prune

# Supprimer les fichiers locaux
rm -rf atelier-cc2
```

## Considérations de Sécurité

1. **Exécution en tant que non-root** : Le Dockerfile crée un utilisateur non-root (`appuser`) pour la sécurité.
2. **Limitez les permissions** : N'exposez que les ports nécessaires (8787, 8788).
3. **Utilisez des montages en lecture seule** : Pour les fichiers de configuration, utilisez des montages en lecture seule :
   ```bash
   -v $(pwd)/config.toml:/home/appuser/app/config.toml:ro
   ```
4. **Gardez Docker à jour** : Mettez régulièrement Docker à jour pour obtenir les derniers correctifs de sécurité.

## Configuration Avancée

### Dockerfile Personnalisé

Vous pouvez personnaliser le Dockerfile pour :
- Ajouter des dépendances supplémentaires
- Changer la version de Python
- Modifier le script d'entrée

### Conteneurs Multiples

Pour des configurations avancées (par exemple, service caméra séparé), vous pouvez étendre le `docker-compose.yml` :

```yaml
version: '3.8'

services:
  atelier-cc2:
    build: .
    ports:
      - "8787:8787"
    volumes:
      - ./models:/home/appuser/app/models
    
  camera:
    image: aler9/rtsp-simple-server
    ports:
      - "8554:8554"
    devices:
      - "/dev/video0:/dev/video0"
```

## Licence

Ce guide fait partie du projet **Atelier CC2**, sous licence **MIT**. Voir [LICENSE](../../LICENSE) pour plus de détails.
