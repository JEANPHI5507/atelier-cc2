#!/bin/bash
# 489 Atelier CC2 - Script d'entrée Docker
# Ce script est exécuté au démarrage du conteneur

set -e

# Installer OrcaSlicer si ce n'est pas déjà fait
if [ ! -f "/home/appuser/app/OrcaSlicer/AppImage/OrcaSlicer" ]; then
    echo "4A1 Installation d'OrcaSlicer..."
    cd /home/appuser/app
    make slicer
fi

# Installer le modèle IA si ce n'est pas déjà fait (optionnel)
if [ ! -d "/home/appuser/app/obico_model" ]; then
    echo "4A1 Installation du modèle IA (optionnel)..."
    cd /home/appuser/app
    make ia || echo "Modèle IA non installé (optionnel)"
fi

# Exécuter la commande principale
exec "$@"
