ORCA_VERSION ?= 2.4.2
ORCA_SHA256  ?= d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd
ORCA_DIR     := tools/orcaslicer
ORCA_URL     := https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v$(ORCA_VERSION)/OrcaSlicer_Linux_AppImage_Ubuntu2404_V$(ORCA_VERSION).AppImage

SERVEUR      ?= Serveur-Maison

.PHONY: install slicer plateau test dash deploy
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

ia:  ## modèle de détection des ratés (Obico, 200 Mo, vérifié)
	uv run python -c "from elegoo_lab import vision; vision.download_model(); print('modèle IA installé')"

# Envoie le code sur le serveur maison (ssh $(SERVEUR), dossier ~/elegoo) et y relance l'atelier.
# La bibliothèque (models/), config.toml, .certs et tools/ du serveur ne sont pas touchés.
deploy:
	rsync -a --delete --exclude __pycache__ src $(SERVEUR):elegoo/
	rsync -a pyproject.toml uv.lock README.md Makefile config.example.toml $(SERVEUR):elegoo/
	ssh $(SERVEUR) 'cd elegoo && ~/.local/bin/uv sync --frozen --no-dev -q && systemctl --user restart cc2-atelier && sleep 6 && systemctl --user is-active cc2-atelier'
