ORCA_VERSION ?= 2.4.2
ORCA_SHA256  ?= d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd
ORCA_DIR     := tools/orcaslicer
ORCA_URL     := https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v$(ORCA_VERSION)/OrcaSlicer_Linux_AppImage_Ubuntu2404_V$(ORCA_VERSION).AppImage

SERVEUR      ?=   # make deploy SERVEUR=<hôte ssh> (une entrée de ~/.ssh/config)

.PHONY: install slicer plateau test dash deploy lint format check all
install:
	uv sync

# Télécharge OrcaSlicer (≈138 Mo), vérifie son empreinte, l'extrait (pas besoin de FUSE).
slicer:
	mkdir -p $(ORCA_DIR)
	test -x $(ORCA_DIR)/squashfs-root/AppRun || { \
	  curl -fL -o $(ORCA_DIR)/OrcaSlicer.AppImage $(ORCA_URL) && \
	  echo "$(ORCA_SHA256)  $(ORCA_DIR)/OrcaSlicer.AppImage" | sha256sum -c - && \
	  chmod +x $(ORCA_DIR)/OrcaSlicer.AppImage && \
	  cd $(ORCA_DIR) && ./OrcaSlicer.AppImage --appimage-extract >/dev/null; }
	$(MAKE) plateau

# Le plateau de la CC2 dans la vue 3D : modèle et marquage d'Elegoo, fournis avec OrcaSlicer (licence AGPL-3.0),
# copiés ici plutôt que versionnés. Sans eux, la vue 3D garde un plateau uni.
PLATE_SRC := $(ORCA_DIR)/squashfs-root/resources/profiles/Elegoo
PLATE_DST := src/elegoo_lab/web/vendor/cc2
plateau:
	mkdir -p $(PLATE_DST)
	cp $(PLATE_SRC)/elegoo_centuri_carbon_buildplate_model.stl $(PLATE_DST)/plateau.stl
	cp $(PLATE_SRC)/elegoo_centuri_carbon_buildplate_texture.svg $(PLATE_DST)/plateau.svg

test:
	uv run pytest -q
dash:
	uv run cc2 --control dash

lint:
	uv run ruff check src/ tests/
	uv run mypy src/elegoo_lab --ignore-missing-imports
	uv run black --check src/ tests/
	uv run isort --check-only src/ tests/

format:
	uv run ruff check --fix src/ tests/
	uv run black src/ tests/
	uv run isort src/ tests/

check:
	uv run pytest -q
	uv run ruff check src/ tests/
	uv run mypy src/elegoo_lab --ignore-missing-imports
	uv run black --check src/ tests/
	uv run isort --check-only src/ tests/

all: lint test

ia:  ## modèle de détection des ratés (Obico, 200 Mo, vérifié)
	uv run python -c "from elegoo_lab import vision; vision.download_model(); print('modèle IA installé')"

# ============================================================================
# Docker
# ============================================================================
DOCKER_IMAGE ?= atelier-cc2
DOCKER_COMPOSE ?= docker-compose

# Construire l'image Docker
docker-build:
	docker build -t $(DOCKER_IMAGE) .

# Exécuter avec le simulateur (mode démo)
docker-simulator:
	docker run -it --rm \
		-p 8788:8788 \
		-v $(pwd)/demo:/home/appuser/app/demo \
		$(DOCKER_IMAGE)

# Exécuter avec une vraie CC2 (remplacer IP et CODE)
docker-cc2:
	@echo "Usage: make docker-cc2 IP=<adresse> CODE=<code>"
	@echo "Example: make docker-cc2 IP=192.168.1.100 CODE=123456"

.PHONY: docker-cc2-impl
docker-cc2-impl:
	docker run -it --rm \
		-p 8787:8787 \
		-v $(pwd)/config.toml:/home/appuser/app/config.toml:ro \
		-v $(pwd)/models:/home/appuser/app/models \
		-v $(pwd)/demo:/home/appuser/app/demo \
		-v $(pwd)/gallery:/home/appuser/app/gallery \
		$(DOCKER_IMAGE) \
		--control dash --ip $(IP) --code $(CODE)

# Démarrer avec Docker Compose (simulateur)
docker-up:
	$(DOCKER_COMPOSE) up -d

# Arrêter Docker Compose
docker-down:
	$(DOCKER_COMPOSE) down

# Voir les logs Docker Composedocker-logs:
	$(DOCKER_COMPOSE) logs -f atelier-cc2

# Construire et démarrer (simulateur)
docker-start:
	$(MAKE) docker-build
	$(MAKE) docker-up

# Nettoyer les images et conteneurs Docker
docker-clean:
	docker system prune -f

# Envoie le code sur le serveur maison (ssh $(SERVEUR), dossier ~/elegoo) et y relance l'atelier.
# La bibliothèque (models/), config.toml, .certs et tools/ du serveur ne sont pas touchés.
deploy:
	@test -n "$(SERVEUR)" || { echo "Indique le serveur : make deploy SERVEUR=<hôte ssh>"; exit 2; }
	rsync -a --delete --exclude __pycache__ src $(SERVEUR):elegoo/
	rsync -a pyproject.toml uv.lock README.md Makefile config.example.toml $(SERVEUR):elegoo/
	ssh $(SERVEUR) 'cd elegoo && ~/.local/bin/uv sync --frozen --no-dev -q && systemctl --user restart cc2-atelier && sleep 6 && systemctl --user is-active cc2-atelier'
