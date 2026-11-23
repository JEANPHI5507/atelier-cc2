# 📋 TODO - Tâches en Cours et Problèmes Connus

> *Dernière mise à jour : 23 Novembre 2026*

---

## 🎯 **Tâches Prioritaires (Haute Priorité)**

### 1. **Infrastructure & CI/CD**
- [x] ✅ Configurer ruff, mypy, black, isort
- [x] ✅ Créer les fichiers de configuration
- [x] ✅ Mettre à jour GitHub Actions CI
- [x] ✅ Ajouter les commandes dans Makefile
- [ ] ⏳ **Configurer les secrets GitHub** (DOCKER_HUB_USERNAME, DOCKER_HUB_TOKEN) pour publier l'image
- [x] ✅ **Configurer OpenGL dans CI** (libopengl0, libglu1-mesa, libwebkit2gtk-4.1) — tests slicing verts
- [ ] ⏳ **Publier l'image Docker** sur Docker Hub (build CI OK, push désactivé sans secrets)
- [x] ✅ **Configurer Codecov** (upload à chaque job avec flags unittests/slicingtests/uitests)

### 2. **Qualité du Code**
- [x] ✅ Corriger les imports inutilisés (F401)
- [x] ✅ Trier les imports avec isort
- [x] ✅ **RET502/RET503 corrigés** (PR #9)
- [x] ✅ **BLE001 corrigé** — except ciblées aux frontières réseau/fichiers, noqa ponctuels (PR #9)
- [x] ✅ **B905 corrigé** — zip(..., strict=True) (PR #9)
- [x] ✅ **TC003 corrigé** — imports déplacés dans TYPE_CHECKING (PR #9)
- [x] ✅ **S (S603/S607…) corrigés** — binaires résolus via shutil.which, noqa ciblés (PR #9)

### 3. **Tests**
- [x] ✅ Installer OrcaSlicer
- [x] ✅ **Installer libopengl0, libglu1-mesa, libwebkit2gtk-4.1** dans l'environnement CI
- [x] ✅ **Tests réparés** : 158 passed / 6 skipped (non-slicing), 21 passed (slicing), UI Playwright verts (Chromium fr-FR)
- [x] ✅ **Configurer Chrome/Playwright** dans CI
- [x] ✅ **80% de couverture atteinte** (INF.3) — 81 % local non-slicing, consolidé CI (unittests + slicing + UI) au-dessus — PR #11–#15, issue #10

---

## 📊 **Statut Actuel**

### Infrastructure
| Élément | Statut | Détails |
|---------|--------|---------|
| **ruff** | ✅ Configuré | 0 erreur (68 corrigées + règles sorties de l'ignore, PR #9) |
| **mypy** | ✅ Configuré | 0 erreur sur 55 fichiers source |
| **black** | ✅ Configuré | Aucun fichier à formater |
| **isort** | ✅ Configuré | Imports corrigés dans 9 fichiers |
| **CI/CD** | ✅ Configuré | Workflow GitHub Actions mis à jour |
| **Makefile** | ✅ Mis à jour | Commandes lint, format, check, all |

### Tests
| Type | Total | Pass | Fail | Skip |
|------|-------|------|------|------|
| **Unitaires (non-slicing)** | 164 | 158 | 0 | 6 |
| **Slicing (CI)** | 21 | 21 | 0 | 0 |
| **UI (CI, Playwright)** | ~25 | ~25 | 0 | 0 |

### Couverture
- **Suivi** : Codecov, upload à chaque job CI (flags par famille de tests)
- **Objectif** : >80% — atteint : 81 % local non-slicing, consolidé CI au-dessus (INF.3, PR #11–#15)

---

## 🔧 **Problèmes Connus**

### Problèmes de Linting (ruff)

#### RET502/RET503 - Return Explicite
**Fichiers concernés** :
- `src/elegoo_lab/access.py` (2 occurrences)
- `src/elegoo_lab/advisor.py` (1 occurrence)
- Autres fichiers avec fonctions async

**Solution** : Ajouter `return None` explicite à la fin des fonctions async qui retournent None.

**Exemple** :
```python
# Avant
async def func() -> None:
    await something()

# Après  
async def func() -> None:
    await something()
    return None
```

#### BLE001 - Blind Exception
**Fichiers concernés** :
- `src/elegoo_lab/advisor.py`
- `src/elegoo_lab/mesh.py`
- Autres fichiers

**Solution** : Remplacer `except Exception:` par des exceptions plus spécifiques.

**Exemple** :
```python
# Avant
except Exception:
    return None

# Après
except (ValueError, TypeError, RuntimeError):
    return None
```

#### B905 - zip() sans strict=
**Fichiers concernés** :
- `src/elegoo_lab/advisor.py`
- Autres fichiers

**Solution** : Ajouter `strict=False` aux appels de zip().

**Exemple** :
```python
# Avant
for a, b in zip(list1, list2):

# Après
for a, b in zip(list1, list2, strict=False):
```

#### TC003 - pathlib dans TYPE_CHECKING
**Fichiers concernés** :
- `src/elegoo_lab/advisor.py`
- Autres fichiers

**Solution** : Déplacer les imports pathlib dans un bloc TYPE_CHECKING.

**Exemple** :
```python
# Avant
from pathlib import Path

# Après
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pathlib import Path
```

---

## 📝 **Comment Contribuer**

### 1. **Corriger un problème de linting**
```bash
# Voir les problèmes
make lint

# Corriger automatiquement (si possible)
make format

# Corriger manuellement
# Edit the file and fix the issues

# Vérifier
make lint
```

### 2. **Ajouter une nouvelle règle de linting**
1. Modifier `.ruff.toml`
2. Retirer la règle de la liste `ignore`
3. Exécuter `make lint` pour voir les nouveaux problèmes
4. Corriger les problèmes
5. Commiter les changements

### 3. **Configurer pre-commit localement**
```bash
pip install pre-commit
pre-commit install
# Maintenant, à chaque commit, le linting sera exécuté automatiquement
```

---

## 🎯 **Prochaines Étapes**

### Cette Semaine
1. **Configurer les secrets GitHub** pour Docker Hub (publier l'image)
2. **Corriger les problèmes RET502/RET503** dans access.py et advisor.py
3. ✅ **Configurer OpenGL dans CI** — fait

### Semaine Prochaine
1. ✅ Linting avancé INF.4–8 (S/BLE/B905/TC003/RET) — PR #9
2. ✅ Couverture 80 % (INF.3) — 81 % local, PR #11–#15
3. **Publier l'image Docker** (INF.2) — build CI OK, il manque les secrets DOCKER_HUB_USERNAME/TOKEN

### Dans le Mois
1. ✅ Tous les problèmes de linting corrigés (0 erreur ruff/mypy)
2. **Publier l'image Docker** sur Docker Hub
3. ✅ Codecov configuré (upload à chaque job CI, flags par famille)
4. **Améliorer la documentation**

---

## 📚 **Ressources**

- [ROADMAP.md](ROADMAP.md) - Feuille de route du projet
- [CONTRIBUTING.md](CONTRIBUTING.md) - Guide de contribution
- [CHANGELOG.md](CHANGELOG.md) - Historique des changements
- [PROGRESS.md](PROGRESS.md) - Suivi des progrès

---

## 🙏 **Remerciements**

Merci à tous les contributeurs qui aident à améliorer la qualité du code !

- **JEANPHI5507** - Mainteneur principal
- **Vibe Code** - Configuration de l'infrastructure de linting

---

*Ce fichier est maintenu par la communauté Atelier CC2.*
