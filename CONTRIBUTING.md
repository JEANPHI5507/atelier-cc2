# 4D6 Contribuer à Atelier CC2

> *Merci de vouloir contribuer à Atelier CC2 ! 64F*
> *Ce guide vous explique comment participer au projet, que vous soyez développeur, testeur, traducteur ou simplement utilisateur.*

---

## 4CD **Sommaire**
1. [Types de Contributions](#types-de-contributions)
2. [Prérequis](#prerequis)
3. [Installation pour le Développement](#installation-pour-le-developpement)
4. [Workflow de Contribution](#workflow-de-contribution)
5. [Bonnes Pratiques](#bonnes-pratiques)
6. [Structure du Code](#structure-du-code)
7. [Tests](#tests)
8. [Documentation](#documentation)
9. [Traductions](#traductions)
10. [Signaler un Bug](#signaler-un-bug)
11. [Proposer une Fonctionnalité](#proposer-une-fonctionnalite)
12. [Code de Conduite](#code-de-conduite)
13. [Licence](#licence)

---

## 4B1 **Types de Contributions**

Nous accueillons tous types de contributions, pas seulement du code ! Voici comment vous pouvez aider :

### 4BB **Développement**
- 489 **Nouveautés** : Ajouter de nouvelles fonctionnalités (voir la [ROADMAP.md](ROADMAP.md)).
- 4A8 **Corrections de bugs** : Résoudre des problèmes existants.
- 4B0 **Optimisations** : Améliorer les performances ou la consommation mémoire.
- 4D6 **Refactoring** : Améliorer la structure du code.
- 527 **Tests** : Ajouter ou améliorer les tests unitaires et d'intégration.

### 4DD **Documentation**
- 4F0 **Guides** : Améliorer ou ajouter des guides dans `/guide/`.
- 4D6 **README** : Mettre à jour la documentation principale.
- 4B1 **FAQ** : Créer une FAQ pour répondre aux questions fréquentes.
- 39F **Tutoriels** : Créer des tutoriels vidéo ou écrits.

### 489 **Traductions**
- 1EC1E7 **Anglais/Français** : Améliorer les traductions existantes.
- 1FA1F8 **Nouvelles langues** : Ajouter le support pour d'autres langues (espagnol, allemand, etc.).

### 469 **Tests et Retours**
- 40D **Tester les nouvelles fonctionnalités** et signaler les bugs.
- 4AC **Donner des retours** sur l'expérience utilisateur.
- 4A1 **Proposer des améliorations** via les issues GitHub.

### 4CC **Autres Contributions**
- 4A8 **Design** : Améliorer l'interface utilisateur (maquettes, icônes).
- 4C4 **Marketing** : Aider à promouvoir le projet (réseaux sociaux, articles).
- 4B0 **Infrastructure** : Améliorer les workflows CI/CD.

---

## 527 **Prérequis**

### 4BB **Pour les Développeurs**
- **Système d'exploitation** : Linux x86-64 (recommandé), ou WSL2 sur Windows.
- **Python** : Version **3.12** (obligatoire).
- **Gestionnaire de paquets** : [uv](https://docs.astral.sh/uv/) (recommandé) ou pip.
- **Outils optionnels** :
  - [OrcaSlicer 2.4.2](https://github.com/SoftFever/OrcaSlicer) (pour la découpe).
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (pour la génération IA).
  - Docker (pour tester en isolation).
  - Node.js (pour vérifier le JavaScript).

### 4CC **Pour les Traducteurs**
- Un éditeur de texte (VS Code, Sublime Text, etc.).
- Connaissance de l'anglais et d'une autre langue.

### 469 **Pour les Testeurs**
- Une **Elegoo Centauri Carbon 2** avec module CANVAS (idéalement).
- Ou utiliser le **simulateur** (`uv run cc2 simulateur`).

---

## 4A7 **Installation pour le Développement**

### 53D **1. Cloner le dépôt**
```bash
 git clone https://github.com/JEANPHI5507/atelier-cc2.git
 cd atelier-cc2
```

### 53D **2. Installer les dépendances**
```bash
# Avec uv (recommandé)
uv sync --all-extras  # Installe toutes les dépendances (y compris dev)

# Avec pip (alternative)
pip install -e .[dev]
```

### 53D **3. Installer OrcaSlicer**
```bash
make slicer  # Télécharge OrcaSlicer 2.4.2 et le plateau CC2
```

### 53D **4. Installer le modèle IA (optionnel)**
```bash
make ia  # Télécharge le modèle de détection de spaghetti d'Obico
```

### 53D **5. Lancer en mode développement**
```bash
# Avec le simulateur (pas besoin d'imprimante)
uv run cc2 simulateur --duree 60

# Avec une vraie CC2 (remplacer IP et CODE par vos valeurs)
uv run cc2 --control dash --ip IP --code CODE
```

### 53D **6. Accéder à l'interface**
Ouvrez votre navigateur à l'adresse :
- **Simulateur** : [http://localhost:8788/lab/](http://localhost:8788/lab/)
- **Vraie CC2** : [http://localhost:8787/lab/](http://localhost:8787/lab/)

---

## 4C3 **Workflow de Contribution**

### 53D **1. Choisir une Tâche**
- Consultez la [ROADMAP.md](ROADMAP.md) pour voir les tâches prioritaires.
- Vérifiez les [issues ouvertes](https://github.com/JEANPHI5507/atelier-cc2/issues) pour trouver des bugs ou des fonctionnalités à implémenter.
- Si vous avez une nouvelle idée, [ouvrez une issue](#proposer-une-fonctionnalite) pour en discuter.

### 53D **2. Créer une Branche**
```bash
# Mettre à jour votre dépôt local
git fetch origin
git checkout main
git pull origin main

# Créer une nouvelle branche (utilisez un nom descriptif)
git checkout -b feature/nom-de-la-fonctionnalite
# ou pour un bug :
git checkout -b fix/nom-du-bug
```

**Conventions de nommage des branches :**
- `feature/...` : Nouvelle fonctionnalité.
- `fix/...` : Correction de bug.
- `refactor/...` : Refactoring du code.
- `docs/...` : Mise à jour de la documentation.
- `chore/...` : Tâches de maintenance (mises à jour de dépendances, etc.).

### 53D **3. Développer**
- **Respectez les conventions de code** (voir [Bonnes Pratiques](#bonnes-pratiques)).
- **Testez vos changements** :
  ```bash
  make test  # Exécute tous les tests
  uv run pytest tests/test_core.py  # Tests spécifiques
  ```
- **Vérifiez le JavaScript** (si vous modifiez le frontend) :
  ```bash
  node --input-type=module --check src/elegoo_lab/web/js/lab.js
  ```

### 53D **4. Commiter vos Changements**
```bash
# Ajouter vos modifications
git add .

# Créer un commit avec un message clair
git commit -m "feat: ajouter la visualisation 3D du CANVAS"
```

**Conventions pour les messages de commit :**
- Utilisez le format [Conventional Commits](https://www.conventionalcommits.org/) :
  - `feat:` : Nouvelle fonctionnalité.
  - `fix:` : Correction de bug.
  - `refactor:` : Refactoring du code.
  - `docs:` : Mise à jour de la documentation.
  - `chore:` : Tâches de maintenance.
  - `test:` : Ajout ou modification de tests.
- **Exemples :**
  - `feat: ajouter le support multi-imprimantes`
  - `fix: corriger le bug de détection de caméra gelée`
  - `docs: mettre à jour le guide d'installation`
  - `refactor: simplifier la gestion des couleurs`

### 53D **5. Pousser vos Changements**
```bash
git push origin feature/nom-de-la-fonctionnalite
```

### 53D **6. Ouvrir une Pull Request (PR)**
1. Allez sur [GitHub](https://github.com/JEANPHI5507/atelier-cc2) et cliquez sur **"Pull Requests"** > **"New Pull Request"**.
2. Sélectionnez votre branche comme **compare branch**.
3. Remplissez le **template de PR** (voir ci-dessous).
4. **Liez votre PR à une issue** (si applicable) en utilisant `Closes #123` ou `Fixes #123`.
5. **Attendez les retours** des mainteneurs et corrigez les éventuels problèmes.

---

## 527 **Bonnes Pratiques**

### 4BB **Code Python**
- **Style** : Suivez les conventions [PEP 8](https://peps.python.org/pep-0008/).
- **Typage** : Utilisez les **type hints** pour les fonctions et les variables.
  ```python
  def calculer_purge(couleur: str, quantite: float) -> float:
      return quantite * 1.1
  ```
- **Docstrings** : Ajoutez des docstrings pour toutes les fonctions publiques (format [Google](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)).
  ```python
  def calculer_purge(couleur: str, quantite: float) -> float:
      """Calcule la quantité de purge nécessaire pour un changement de couleur.
      
      Args:
          couleur: La couleur actuelle.
          quantite: La quantité de filament à purger.
          
      Returns:
          La quantité de purge calculée.
      """
      return quantite * 1.1
  ```
- **Gestion des erreurs** : Utilisez des exceptions personnalisées pour les erreurs spécifiques.
- **Logging** : Utilisez le module `logging` pour les messages de debug.
- **Pas de commentaires inutiles** : Les commentaires doivent expliquer **pourquoi**, pas **quoi** (le code doit être auto-documenté).

### 4BB **Code JavaScript**
- **Style** : Suivez les conventions [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript).
- **ES Modules** : Utilisez `import`/`export` pour les modules modernes.
- **Vérification** : Vérifiez votre code avec `node --check` avant de commiter.
- **Pas de jQuery** : Préférez le JavaScript vanilla ou des frameworks modernes (si nécessaire).

### 4BB **Code HTML/CSS**
- **Sémantique** : Utilisez des balises HTML sémantiques (`<section>`, `<article>`, etc.).
- **Accessibilité** : Respectez les règles [WCAG](https://www.w3.org/WAI/standards-guidelines/wcag/) (contraste, navigation au clavier, etc.).
- **CSS** : Évitez les styles inline. Utilisez des classes et des IDs clairs.

### 4BB **Gestion des Dépendances**
- **Ajouter une dépendance** :
  - Ajoutez-la dans `pyproject.toml` (pour Python).
  - Ou dans `package.json` (pour JavaScript).
  - **Justifiez** son ajout dans la PR (pourquoi cette dépendance est nécessaire ?).
- **Éviter les dépendances lourdes** : Préférez des alternatives légères si possible.
- **Mettre à jour les dépendances** : Utilisez `uv lock` pour mettre à jour `uv.lock`.

### 4BB **Sécurité**
- **Ne jamais commiter de secrets** (mots de passe, clés API, etc.).
- **Utilisez des variables d'environnement** pour les configurations sensibles.
- **Validez les entrées utilisateur** : Ne faites pas confiance aux données envoyées par le client.
- **Échappez les sorties** : Utilisez des templates sécurisés pour éviter les injections XSS.

---

## 4CA **Structure du Code**

```
src/elegoo_lab/
├── cli.py              # Interface en ligne de commande (cc2)
├── app.py              # Serveur web (FastAPI)
├── config.py           # Gestion de la configuration (config.toml)
├── slicer.py           # Intégration avec OrcaSlicer
├── printprep.py        # Préparation des modèles pour l'impression
├── colors.py           # Gestion des couleurs et du CANVAS
├── colorize.py         # Assemblage des pièces en 3MF multicolore
├── mesh.py             # Manipulation des maillages 3D
├── launch.py           # Lancement des impressions
├── alerts.py           # Système d'alertes et notifications
├── vision.py           # Détection IA (spaghetti)
├── camfeed.py          # Gestion du flux caméra
├── simulateur.py       # Simulateur de CC2
├── comfy.py            # Intégration avec ComfyUI
└── web/                # Frontend
    ├── index.html      # Structure de l'interface
    ├── js/             # JavaScript
    │   ├── core.js     # Fonctions utilitaires
    │   ├── lab.js      # Logique de l'atelier
    │   ├── printer.js  # Onglet Imprimante
    │   └── ...
    ├── css/            # Styles CSS
    │   └── app.css     # Styles principaux
    └── vendor/         # Bibliothèques tierces (three.js)
```

---

## 527 **Tests**

### 4A7 **Exécuter les Tests**
```bash
# Tous les tests
make test

# Tests spécifiques
uv run pytest tests/test_core.py    # Tests backend
uv run pytest tests/test_ui.py      # Tests frontend (nécessite Playwright)
```

### 4B0 **Écrire des Tests**
- **Tests unitaires** : Utilisez `pytest` pour tester les fonctions individuelles.
- **Tests d'intégration** : Testez les interactions entre composants.
- **Tests UI** : Utilisez [Playwright](https://playwright.dev/) pour tester l'interface.

**Exemple de test unitaire :**
```python
# tests/test_colors.py
def test_calculer_purge():
    from elegoo_lab.colors import calculer_purge
    assert calculer_purge("rouge", 10.0) == 11.0
```

**Exemple de test UI (Playwright) :**
```python
# tests/test_ui.py
def test_connexion_cc2(page):
    page.goto("http://localhost:8788/lab/")
    page.fill("#ip-input", "192.168.1.100")
    page.fill("#code-input", "123456")
    page.click("#connect-button")
    assert "Connecté" in page.content()
```

### 4A1 **Couverture de Code**
- **Objectif** : Atteindre **80% de couverture** pour le code critique.
- **Outil** : Utilisez `pytest-cov` pour mesurer la couverture.
  ```bash
  uv run pytest --cov=src/elegoo_lab --cov-report=html
  ```

---

## 4D6 **Documentation**

### 4F0 **Mettre à Jour la Documentation**
- **Guides** : Dans `/guide/` (EN/FR).
- **README** : Dans `README.md` et `README.fr.md`.
- **ROADMAP** : Dans `ROADMAP.md`.
- **API** : Si vous ajoutez des endpoints, documentez-les dans `/docs/api.md`.

### 4DD **Format des Guides**
- Utilisez le **Markdown** pour la mise en forme.
- **Structure** :
  ```markdown
  # Titre du Guide
  
  ## Introduction
  Description du sujet.
  
  ## Prérequis
  Ce qui est nécessaire avant de commencer.
  
  ## Étapes
  1. Première étape.
  2. Deuxième étape.
  
  ## Dépannage
  Solutions aux problèmes courants.
  ```

---

## 1FA1F8 **Traductions**

### 4B1 **Structure des Traductions**
- **Frontend** : Fichiers JSON dans `/src/elegoo_lab/web/i18n/`.
  - `en.json` : Anglais (référence).
  - `fr.json` : Français.
- **Notifications** : Dans `/src/elegoo_lab/i18n.py`.

### 489 **Ajouter une Nouvelle Langue**
1. Copiez `en.json` vers `xx.json` (où `xx` est le code de la langue).
2. Traduisiez toutes les chaînes de caractères.
3. Mettez à jour `i18n.py` pour supporter la nouvelle langue.

### 4A1 **Vérifier les Traductions**
- **Outil** : Utilisez un script pour détecter les chaînes non traduites.
  ```bash
  # Exemple : Comparer en.json et fr.json
  diff src/elegoo_lab/web/i18n/en.json src/elegoo_lab/web/i18n/fr.json
  ```

---

## 41B **Signaler un Bug**

1. **Vérifiez que le bug n'a pas déjà été signalé** :
   - Consultez les [issues ouvertes](https://github.com/JEANPHI5507/atelier-cc2/issues).
2. **Collectez des informations** :
   - Version de l'OS.
   - Version de Python (`python --version`).
   - Version d'Atelier CC2 (`git log --oneline -1`).
   - Étapes pour reproduire le bug.
   - Comportement attendu vs. comportement réel.
   - Logs d'erreur (si disponibles).
3. **Ouvrez une issue** :
   - Utilisez le [template de bug](#) (disponible lors de la création d'une issue).
   - Ajoutez des **labels** (`bug`, `priorité:haute`, etc.).

---

## 4A1 **Proposer une Fonctionnalité**

1. **Vérifiez que la fonctionnalité n'a pas déjà été proposée** :
   - Consultez les [issues](https://github.com/JEANPHI5507/atelier-cc2/issues) et la [ROADMAP.md](ROADMAP.md).
2. **Décrivez votre idée** :
   - Quel est le **problème** que cela résout ?
   - Quelle est la **solution** proposée ?
   - Quels sont les **avantages** ?
   - Y a-t-il des **alternatives** existantes ?
3. **Ouvrez une issue** :
   - Utilisez le [template de feature request](#).
   - Ajoutez le label `enhancement`.

---

## 469 **Code de Conduite**

Nous suivons le [Code de Conduite des Contributeurs](https://www.contributor-covenant.org/version/2/0/code_of_conduct.html).

**Règles de base :**
- Soyez **respectueux** envers les autres contributeurs.
- Soyez **constructif** dans vos retours.
- **Collaborez** plutôt que de critiquer.
- **Documentez** vos changements.
- **Testez** vos contributions.

---

## 3F3 **Licence**

Ce projet est sous licence **MIT**. En contribuant, vous acceptez que vos contributions soient également sous licence MIT.

---

## 489 **Remerciements**

Merci à tous les contributeurs qui rendent ce projet possible ! 64F

---

*Pour toute question, n'hésitez pas à ouvrir une issue ou à nous contacter via les discussions GitHub.*
