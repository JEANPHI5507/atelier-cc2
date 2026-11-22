# 489 Atelier CC2 - Dockerfile
# Image Docker pour exécuter Atelier CC2

FROM python:3.12-slim

# Installer les dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Pour OrcaSlicer (AppImage)
    libfuse2 \
    libgl1 \
    libglib2.0-0 \
    # Pour la caméra (optionnel)
    libcamera-dev \
    # Pour les polices
    fonts-dejavu \
    fonts-liberation \
    # Outils utiles
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Créer un utilisateur non-root
RUN useradd -m -u 1000 appuser
WORKDIR /home/appuser/app

# Copier les fichiers du projet
COPY --chown=appuser:appuser . .

# Copier le script d'entrée
COPY docker-entrypoint.sh /home/appuser/app/docker-entrypoint.sh
RUN chmod +x /home/appuser/app/docker-entrypoint.sh

# Définir l'utilisateur
USER appuser

# Installer uv et les dépendances Python
RUN pip install uv && \
    uv sync --frozen

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/home/appuser/app/.venv/bin:$PATH"

# Ports exposés
EXPOSE 8787 8788

# Commande par défaut (simulateur)
ENTRYPOINT ["/home/appuser/app/docker-entrypoint.sh"]
CMD ["uv", "run", "cc2", "simulateur"]
