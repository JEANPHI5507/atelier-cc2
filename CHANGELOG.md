# 📜 Changelog - Atelier CC2

> *Suivi des changements et des versions du projet*

---

## 📋 Format

Ce changelog suit les conventions de [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/).

Les versions suivent la [Semantic Versioning](https://semver.org/) : `MAJOR.MINOR.PATCH`
- **MAJOR** : Changements incompatibles avec les versions précédentes
- **MINOR** : Ajout de fonctionnalités (rétrocompatibles)
- **PATCH** : Corrections de bugs (rétrocompatibles)

---

## 🚀 [Unreleased]

### 🐛 Corrigé
- Le bouton « Lancer l'impression » du Workflow guidé envoyait l'ordre sans contrôle (plateau, bobines, stock, imprimante occupée) ni envoi du fichier : il ouvre maintenant le dialogue de lancement

### ✨ Ajouté
- R3.7 : vérification du niveau de filament avant impression — `POST /print/start` refuse (409) un lancement si une bobine n'a pas assez de filament, sauf `ignore_stock` ; alerte « marge faible » (< 20 g ou < 10 %) ; `POST /lab/api/print/stock` refait le calcul quand on change de bobine ; case « Lancer quand même » dans le dialogue
- Ajout des outils de linting : ruff, mypy, black, isort
- Configuration CI/CD améliorée avec linting automatisé
- Fichiers de configuration : `.ruff.toml`, `.mypy.ini`, `.pre-commit-config.yaml`
- Commandes Makefile étendues : `make lint`, `make format`, `make check`, `make all`

### 🔧 Modifié
- Mise à jour de `pyproject.toml` avec les dépendances de développement
- Mise à jour de `.github/workflows/ci.yml` pour inclure le linting
- Amélioration de la configuration des tests

### 🐛 Corrigé
- Correction des tests nécessitant OrcaSlicer (en attente de libopengl0)

---

## 🏷️ [0.2.0] - 2024-11-22

### ✨ Ajouté
- **Phase 1 - Stabilité & Portabilité** (en cours)
  - ✅ R1.1: Dockerisation complète avec Makefile
  - ✅ R1.2: Guide d'installation WSL2 pour Windows
  - ✅ R1.3: Mode Safe Firmware pour CC2
  - ✅ R1.4: Outil `cc2 doctor` étendu
- ROADMAP.md complète avec 5 phases de développement
- PROGRESS.md pour le suivi des tâches
- CONTRIBUTING.md détaillé
- Infrastructure de contribution complète

### 🔧 Modifié
- Amélioration de la documentation
- Structure du projet optimisée
- Configuration Docker améliorée

---

## 🏷️ [0.1.0] - 2024-11-20

### ✨ Ajouté
- Version initiale de l'Atelier CC2
- Fonctionnalités de base :
  - Préparation des modèles 3D multicolores
  - Intégration avec OrcaSlicer
  - Tableau de bord web
  - Suivi des impressions
  - Caméra avec détection IA (Obico)
  - Notifications
  - Galerie des impressions
  - Assistant IA
  - Mode simulateur

### 📝 Documentation
- README.md (FR/EN)
- Guides techniques (14 guides)
- Documentation de l'API

---

## 📊 Statistiques

| Version | Date | Commits | Contributeurs | Lignes de code |
|---------|------|---------|---------------|----------------|
| 0.2.0 | 2024-11-22 | +10 | 1 | ~13,061 |
| 0.1.0 | 2024-11-20 | Initial | 1 | ~12,000 |

---

## 🎯 Roadmap

Voir [ROADMAP.md](ROADMAP.md) pour les versions futures.

---

## 📦 Comment contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour les instructions de contribution.

---

*Ce changelog est généré manuellement et maintenu par la communauté Atelier CC2.*
