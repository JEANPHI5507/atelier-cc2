# Guide d'Installation WSL2 pour Windows

[\u2190 Retour au README](../README.fr.md) \u00b7 \ud83c\uddec\ud83c\udde7 [English](en/wsl2.md)

## Présentation

Ce guide explique comment exécuter **Atelier CC2** sur **Windows 10/11** en utilisant **WSL2 (Windows Subsystem for Linux 2)**. C'est la méthode recommandée pour les utilisateurs Windows.

## Prérequis

- **Windows 10 version 2004 ou ultérieure** (Build 19041 ou supérieur)
- **Windows 11** (n'importe quelle version)
- **Accès administrateur** (pour l'installation de WSL2)
- **4 Go de RAM minimum** (recommandé : 8 Go)
- **20 Go d'espace disque libre** (pour WSL2 et les dépendances)

## Étape 1 : Activer WSL2

### Option A : Utilisation de PowerShell (Recommandé)

Ouvrez **PowerShell en tant qu'administrateur** et exécutez :

```powershell
# Activer WSL2 et installer Ubuntu (distribution par défaut)
wsl --install

# Définir WSL2 comme version par défaut
wsl --set-default-version 2
```

### Option B : Installation Manuelle

1. **Activer la plateforme de machine virtuelle** (si ce n'est pas déjà fait) :
   ```powershell
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```

2. **Activer WSL** :
   ```powershell
   dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
   ```

3. **Redémarrez votre ordinateur**

4. **Télécharger et installer la mise à jour du noyau WSL2** :
   - [Télécharger depuis Microsoft](https://aka.ms/wsl2kernel)

5. **Définir WSL2 comme version par défaut** :
   ```powershell
   wsl --set-default-version 2
   ```

6. **Installer une distribution Linux** (par exemple, Ubuntu) :
   - Ouvrez le Microsoft Store
   - Recherchez "Ubuntu" et installez-le
   - Ou utilisez PowerShell :
     ```powershell
     wsl --install -d Ubuntu
     ```

## Étape 2 : Installer Docker Desktop

1. **Télécharger Docker Desktop pour Windows** :
   - [Télécharger depuis Docker](https://docs.docker.com/docker-for-windows/install/)

2. **Installer Docker Desktop** :
   - Exécutez l'installateur
   - Suivez les étapes d'installation

3. **Activer l'intégration WSL2** :
   - Ouvrez Docker Desktop
   - Allez dans **Paramètres > Ressources > Intégration WSL**
   - Activez l'intégration avec votre distribution WSL2 (par exemple, Ubuntu)
   - Cliquez sur **Appliquer et redémarrer**

## Étape 3 : Configurer l'Environnement WSL2

### Ouvrir le Terminal WSL2

1. Appuyez sur **Win + R**, tapez `wsl` et appuyez sur Entrée
2. Ou ouvrez **Ubuntu** depuis le menu Démarrer

### Mettre à Jour le Système

```bash
# Mettre à jour les listes de paquets
sudo apt update && sudo apt upgrade -y

# Installer les dépendances de base
sudo apt install -y git curl wget build-essential python3-pip python3-venv
```

### Installer uv (Gestionnaire de Paquets Python)

```bash
# Installer uv (gestionnaire de paquets recommandé pour ce projet)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ajouter uv au PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Étape 4 : Cloner et Configurer Atelier CC2

```bash
# Cloner le dépôt
git clone https://github.com/JEANPHI5507/atelier-cc2.git
cd atelier-cc2

# Installer les dépendances Python
uv sync

# Installer OrcaSlicer
make slicer

# Optionnel : Installer le modèle IA pour la détection de "spaghetti"
make ia
```

## Étape 5 : Exécuter Atelier CC2

### Option A : Utilisation de Docker (Recommandé)

```bash
# Construire l'image Docker
docker build -t atelier-cc2 .

# Exécuter avec le simulateur (mode démo)
docker run -it --rm -p 8788:8788 atelier-cc2

# Puis ouvrez votre navigateur à l'adresse : http://localhost:8788/lab/
```

### Option B : Directement dans WSL2

```bash
# Exécuter avec le simulateur (mode démo)
uv run cc2 simulateur

# Puis ouvrez votre navigateur à l'adresse : http://localhost:8788/lab/

# Exécuter avec une vraie CC2 (remplacez IP et CODE par les valeurs de votre imprimante)
uv run cc2 --control dash --ip 192.168.1.100 --code 123456

# Puis ouvrez votre navigateur à l'adresse : http://localhost:8787/lab/
```

## Étape 6 : Accéder depuis le Navigateur Windows

Lorsque vous exécutez Atelier CC2 dans WSL2, vous pouvez y accéder depuis votre navigateur Windows en utilisant :
- **http://localhost:8787/lab/** (pour une vraie imprimante)
- **http://localhost:8788/lab/** (pour le simulateur)

Cela fonctionne car WSL2 redirige automatiquement les ports localhost vers l'hôte Windows.

## Résolution des Problèmes

### "WSL2 nécessite une mise à jour de son composant noyau"

Téléchargez et installez la dernière mise à jour du noyau WSL2 :
- [Mise à jour du noyau WSL2](https://aka.ms/wsl2kernel)

Puis redémarrez votre ordinateur.

### "Erreur : 0x80370102 La machine virtuelle n'a pas pu être démarrée"

1. Assurez-vous que **la plateforme de machine virtuelle** est activée :
   ```powershell
   dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
   ```

2. Assurez-vous que **Hyper-V** est activé :
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
   ```

3. Redémarrez votre ordinateur

### "Docker Desktop nécessite WSL2"

1. Assurez-vous que WSL2 est défini comme version par défaut :
   ```powershell
   wsl --set-default-version 2
   ```

2. Redémarrez Docker Desktop

### "Permission Denied" Lors de l'Exécution de Docker

Assurez-vous que votre utilisateur fait partie du groupe **docker** :

```bash
# Dans WSL2
sudo usermod -aG docker $USER
newgrp docker
```

Puis redémarrez votre terminal WSL2.

### "No such file or directory" Lors de l'Exécution de make

Assurez-vous d'avoir **make** installé :

```bash
sudo apt install -y make
```

### "uv: command not found"

Assurez-vous que uv est dans votre PATH :

```bash
# Ajouter à ~/.bashrc si ce n'est pas déjà fait
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Port Déjà Utilisé

Vérifiez quel processus utilise le port :

```powershell
# Sur Windows
netstat -ano | findstr 8788
```

Puis soit arrêtez le processus conflictuel, soit utilisez un autre port.

## Conseils de Performance

### Augmenter la Limite de Mémoire WSL2

1. Créez ou éditez `~/.wslconfig` dans votre **profil utilisateur Windows** (pas dans WSL2) :

   ```ini
   [wsl2]
   memory=8GB    # Limite la VM à 8 Go de RAM
   processors=4  # Limite la VM à 4 cœurs CPU
   swap=4GB      # Limite l'espace swap à 4 Go
   ```

2. Redémarrez WSL2 :
   ```powershell
   wsl --shutdown
   ```

### Augmenter les Ressources Docker

1. Ouvrez Docker Desktop
2. Allez dans **Paramètres > Ressources**
3. Augmentez la **mémoire** à au moins 4 Go (recommandé : 8 Go)
4. Augmentez les **CPU** à au moins 2 (recommandé : 4)
5. Cliquez sur **Appliquer et redémarrer**

### Utiliser un Disque Séparé pour WSL2

Si vous avez un disque secondaire, vous pouvez y stocker WSL2 :

1. Exportez votre distribution WSL2 :
   ```powershell
   wsl --export Ubuntu ubuntu.tar
   ```

2. Déplacez le fichier vers votre disque secondaire :
   ```powershell
   move ubuntu.tar D:\wsl\ubuntu.tar
   ```

3. Importez-le à nouveau :
   ```powershell
   wsl --import Ubuntu D:\wsl\ubuntu ubuntu.tar --version 2
   ```

4. Définissez comme distribution par défaut :
   ```powershell
   wsl --set-default Ubuntu
   ```

## Accès aux Fichiers depuis Windows

Vous pouvez accéder à vos fichiers WSL2 depuis l'Explorateur Windows en naviguant vers :
```
\\wsl$\Ubuntu\home\<votre-nom-d-utilisateur>\atelier-cc2
```

## Mise à Jour

Pour mettre à jour Atelier CC2 :

```bash
# Dans WSL2
cd atelier-cc2
git pull origin main
uv sync
```

Si vous utilisez Docker :

```bash
# Dans WSL2
cd atelier-cc2
git pull origin main
docker build -t atelier-cc2 . --no-cache
```

## Désinstallation

Pour supprimer complètement Atelier CC2 de WSL2 :

```bash
# Dans WSL2
rm -rf atelier-cc2
```

Pour supprimer WSL2 :

```powershell
# Dans PowerShell en tant qu'administrateur
wsl --unregister Ubuntu
wsl --shutdown
```

## Considérations de Sécurité

1. **Gardez WSL2 à jour** : Mettez régulièrement votre distribution WSL2 à jour :
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Utilisez des mots de passe robustes** : Définissez un mot de passe robuste pour votre utilisateur WSL2

3. **Limitez les permissions Docker** : N'exposez que les ports nécessaires

4. **Utilisez le pare-feu** : Assurez-vous que le pare-feu Windows est activé

## Licence

Ce guide fait partie du projet **Atelier CC2**, sous licence **MIT**. Voir [LICENSE](../../LICENSE) pour plus de détails.
