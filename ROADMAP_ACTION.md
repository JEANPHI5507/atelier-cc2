# 🎯 ROADMAP ACTION - Atelier CC2

> *Générée le 24 Novembre 2024*
> *Basée sur l'analyse du dépôt et des fichiers existants (ROADMAP.md, TODO.md, PROGRESS.md)*

---

## 📊 **État Actuel du Projet**

### ✅ **Ce qui est déjà fait**
- **Infrastructure de linting** : ruff, mypy, black, isort configurés et fonctionnels
- **CI/CD** : GitHub Actions configuré
- **Code principal** : 0 erreur ruff (tout est clean dans `src/`)
- **Phase 0 (débloquer la CI)** : ✅ terminée (PR #2, #3 — CI 100% verte et bloquante, mypy 0 erreur, slicing/UI OK)
- **Phase 1** : ✅ **100% complète (6/6 tâches terminées)**
  - ✅ R1.1 : Dockerisation
  - ✅ R1.2 : Support WSL2
  - ✅ R1.3 : Mode Safe Firmware
  - ✅ R1.4 : Outil cc2 doctor étendu
  - ⚠️ R1.5 : Documentation des limites CC2 (PR #4, issue #6) ✅
  - ❌ R1.6 : Gestion des erreurs caméra (PR #7, issue #5) ✅

### ⚠️ **Points Bloquants Identifiés**

| Catégorie | Problème | Impact | Priorité | Solution |
|----------|----------|--------|----------|----------|
| **Linting** | 273 erreurs dans les tests | CI échoue | 🔴 **Haute** | Corriger ou ignorer dans pyproject.toml |
| **Tests** | 11 tests échoués (dépendances système) | CI incomplète | 🔴 **Haute** | Configurer OpenGL, Chrome |
| **CI** | OpenGL manquant pour tests slicing | Tests slicing bloqués | 🔴 **Haute** | Installer libopengl0, libglu1-mesa |
| **CI** | Chrome manquant pour Playwright | Tests UI bloqués | 🔴 **Haute** | Configurer Chrome dans CI |
| **Couverture** | Codecov non configuré | Pas de suivi de couverture | 🟡 **Moyenne** | Configurer Codecov |
| **Docker** | Image non publiée | Pas de déploiement facile | 🟡 **Moyenne** | Publier sur Docker Hub |
| **Documentation** | R1.5 terminée (PR #4) | - | ✅ | - |

### 📈 **Statistiques**
- **Code source** : 51 fichiers Python, ~13K lignes
- **Tests** : 138 tests (86 pass, 6 skip, 56 fail)
- **Couverture** : ~60% (objectif : >80%)
- **Erreurs ruff** : 0 dans src/, 273 dans tests/

---

## 🎯 **ROADMAP PRIORISÉE**

### 🔴 **PHASE 0 : DÉBLOQUER LA CI (Priorité Absolue)**
**Objectif** : Avoir une CI qui passe complètement (linting + tests)
**Durée estimée** : 1-2 jours
**Statut** : ✅ **Terminée** (PR #2, #3 — CI 100% verte, mypy 0, slicing/UI OK)

| ID | Tâche | Description | Complexité | Statut | Dépendances |
|----|-------|-------------|------------|--------|-------------|
| **A0.1** | Configurer ignores ruff pour tests | Ajouter PT018, E702, PT011, ARG005, etc. dans per-file-ignores | ⭐⭐ | ✅ Fait | Aucune |
| **A0.2** | Configurer OpenGL dans CI | Installer libopengl0 et libglu1-mesa dans le workflow CI | ⭐⭐⭐ | ✅ Fait | Aucune |
| **A0.3** | Configurer Chrome pour Playwright | Installer Chrome et ses dépendances dans CI | ⭐⭐⭐ | ✅ Fait | Aucune |
| **A0.4** | Corriger les 11 tests échoués | Analyser et corriger les tests qui échouent | ⭐⭐⭐ | ✅ Fait | A0.2, A0.3 |
| **A0.5** | Vérifier que CI passe | Exécuter la CI complète et corriger les derniers problèmes | ⭐⭐ | ✅ Fait | A0.1-A0.4 |

**Livrables Phase 0 :**
- [x] CI passe avec ✅ (linting + tous les tests)
- [x] Workflow GitHub Actions fonctionnel
- [ ] Documentation mise à jour (guide de développement)

---

### 🟡 **PHASE 1 : FINALISER LA PHASE 1 (Priorité Haute)**
**Objectif** : Terminer les 2 tâches restantes de la Phase 1
**Durée estimée** : 3-5 jours
**Statut** : ✅ **Terminée (6/6)**

| ID | Tâche | Description | Complexité | Statut | Dépendances |
|----|-------|-------------|------------|--------|-------------|
| **R1.5** | Documentation des limites CC2 | Ajouter une section claire dans l'UI sur les commandes bloquées | ⭐⭐ | ✅ Fait (PR #4, issue #6) | Aucune |
| **R1.6** | Gestion des erreurs caméra | Détection automatique des caméras gelées + redémarrage | ⭐⭐⭐ | ✅ Fait (PR #7, issue #5) | Aucune |

**Livrables Phase 1 :**
- [x] Documentation complète des limites CC2
- [x] Système de détection et redémarrage des caméras
- [x] Phase 1 à 100% complète

---

### 🟡 **PHASE 2 : INFRASTRUCTURE & QUALITÉ (Priorité Moyenne)**
**Objectif** : Améliorer la qualité du code et l'infrastructure
**Durée estimée** : 1-2 semaines
**Statut** : ⏳ **À venir**

| ID | Tâche | Description | Complexité | Statut | Dépendances |
|----|-------|-------------|------------|--------|-------------|
| **INF.1** | Configurer Codecov | Ajouter le token et configurer le suivi de couverture | ⭐⭐ | ⏳ À faire | Phase 0 |
| **INF.2** | Publier l'image Docker | Configurer et publier sur Docker Hub | ⭐⭐⭐ | ⏳ À faire | Phase 0 |
| **INF.3** | Atteindre 80% de couverture | Ajouter des tests pour atteindre l'objectif | ⭐⭐⭐⭐ | ✅ Terminé (#11–#15, #10) — 81 % local non-slicing | INF.1 |
| **INF.4** | Corriger problèmes S* (sécurité) | Corriger S101, S301, S307, S603, S607 | ⭐⭐⭐ | ✅ Terminé (#9) | Aucune |
| **INF.5** | Corriger RET502/RET503 | Ajouter return None explicite dans les fonctions async | ⭐⭐ | ✅ Terminé (#9) | Aucune |
| **INF.6** | Corriger BLE001 | Remplacer except Exception par des exceptions spécifiques | ⭐⭐⭐ | ✅ Terminé (#9) | Aucune |
| **INF.7** | Corriger B905 | Ajouter strict=False aux appels de zip() | ⭐ | ✅ Terminé (#9) | Aucune |
| **INF.8** | Corriger TC003 | Déplacer pathlib dans TYPE_CHECKING | ⭐⭐ | ✅ Terminé (#9) | Aucune |

**Livrables Phase 2 :**
- [x] Codecov configuré et fonctionnel (upload à chaque job CI, codecov.yml)
- [ ] Image Docker publiée sur Docker Hub (INF.2 : secrets DOCKER_HUB_* à configurer)
- [x] 80% de couverture de code (81 % local non-slicing, PR #11–#15)
- [x] Tous les problèmes de linting corrigés (ruff/mypy 0 erreur, PR #9)
- [x] Code plus sécurisé et maintenable (PR #9)

---

### 🟢 **PHASE 3 : EXPÉRIENCE UTILISATEUR (Priorité Moyenne)**
**Objectif** : Rendre l'outil accessible et intuitif
**Durée estimée** : 2-3 mois
**Statut** : ⏳ **À venir**

| ID | Tâche | Description | Complexité | Statut | Dépendances |
|----|-------|-------------|------------|--------|-------------|
| **R2.1** | Mode Débutant | Masquer les options avancées pour les nouveaux utilisateurs | ⭐⭐⭐ | ✅ Terminé (#17, #16) | Phase 1 |
| **R2.2** | Visualisation CANVAS 3D | Schéma interactif des 4 bobines avec couleurs actuelles | ⭐⭐⭐⭐ | ⏳ À faire | Phase 1 |
| **R2.3** | Notifications Intelligentes | Niveaux de priorité (Critique/Avertissement/Info) + historique | ⭐⭐⭐ | ⏳ À faire | Phase 1 |
| **R2.4** | Backup Automatique | Sauvegarde de config.toml et bibliothèque avec versioning | ⭐⭐ | ⏳ À faire | Phase 1 |
| **R2.5** | Assistant Guidé | Étendre le chat pour proposer des workflows pas à pas | ⭐⭐⭐⭐ | ⏳ À faire | Phase 1 |

**Livrables Phase 3 :**
- [x] Interface simplifiée pour les débutants (mode Débutant, PR #17)
- [ ] Visualisation interactive du CANVAS
- [ ] Système de notifications amélioré
- [ ] Système de backup automatique
- [ ] Assistant guidé étendu

---

### 🟢 **PHASE 4 : FONCTIONNALITÉS AVANCÉES (Priorité Moyenne)**
**Objectif** : Ajouter des fonctionnalités demandées par la communauté
**Durée estimée** : 3-4 mois
**Statut** : ⏳ **À venir**

| ID | Tâche | Description | Complexité | Statut | Dépendances |
|----|-------|-------------|------------|--------|-------------|
| **R3.1** | Gestion Multi-Imprimantes | Sélecteur d'imprimante + configurations par imprimante | ⭐⭐⭐⭐ | ⏳ À faire | Phase 2 |
| **R3.2** | Planification des Impressions | Calendrier pour programmer des impressions | ⭐⭐⭐⭐ | ⏳ À faire | Phase 2 |
| **R3.3** | Intégration Thingiverse/Printables | Import direct depuis les plateformes via API | ⭐⭐⭐⭐ | ⏳ À faire | Phase 2 |
| **R3.4** | Partage de Profils | Exporter/importer les profils en JSON | ⭐⭐ | ⏳ À faire | Phase 2 |

---

## 📅 **CALENDRIER PRÉVISIONNEL**

| Phase | Début | Fin | Durée | Statut |
|-------|-------|-----|-------|--------|
| **Phase 0** | 24 Nov 2024 | 25 Nov 2024 | 2 jours | 🔴 **Priorité Absolue** |
| **Phase 1** | 26 Nov 2024 | 30 Nov 2024 | 5 jours | 🟡 **Priorité Haute** |
| **Phase 2** | 1 Déc 2024 | 15 Déc 2024 | 2 semaines | 🟡 **Priorité Moyenne** |
| **Phase 3** | 16 Déc 2024 | 28 Fév 2025 | 2.5 mois | 🟢 **À venir** |
| **Phase 4** | 1 Mar 2025 | 30 Avr 2025 | 2 mois | 🟢 **À venir** |

---

## 🚀 **PLAN D'ACTION IMMEDIAT (Next Steps)**

### **Aujourd'hui (24 Nov 2024)**
1. ✅ **Analyser le projet** - TERMINÉ
2. 🔄 **Créer cette roadmap** - EN COURS
3. ⏳ **Corriger les problèmes de linting dans les tests** (A0.1)
4. ⏳ **Configurer OpenGL dans CI** (A0.2)
5. ⏳ **Configurer Chrome pour Playwright** (A0.3)

### **Demain (25 Nov 2024)**
1. ⏳ **Corriger les 11 tests échoués** (A0.4)
2. ⏳ **Vérifier que CI passe** (A0.5)
3. ⏳ **Commencer R1.5** (Documentation des limites CC2)

### **Cette semaine**
1. ⏳ **Terminer Phase 0** (CI fonctionnelle)
2. ⏳ **Terminer Phase 1** (100% complète)
3. ⏳ **Commencer Phase 2** (Codecov, Docker)

---

## 📋 **TÂCHES PAR CONTRIBUTEUR**

### **Pour Vibe Code (Agent IA)**
- [ ] Corriger les problèmes de linting dans les tests (A0.1)
- [ ] Configurer OpenGL dans CI (A0.2)
- [ ] Configurer Chrome pour Playwright (A0.3)
- [ ] Corriger les 11 tests échoués (A0.4)
- [x] Configurer Codecov (INF.1)
- [ ] Publier l'image Docker (INF.2 — secrets à ajouter)
- [x] Corriger les problèmes de sécurité (INF.4, PR #9)

### **Pour JEANPHI5507 (Mainteneur)**
- [ ] Revoir et merger les PR
- [ ] Terminer R1.5 (Documentation des limites CC2)
- [ ] Terminer R1.6 (Gestion des erreurs caméra)
- [ ] Configurer les secrets GitHub (Docker Hub, Codecov)

### **Pour la Communauté**
- [ ] Tester les nouvelles fonctionnalités
- [ ] Signaler les bugs
- [ ] Contribuer à la documentation
- [ ] Proposer des améliorations

---

## 🎉 **CRITÈRES DE SUCCÈS**

### **Phase 0 (CI)**
- [ ] `make lint` passe sans erreur
- [ ] `make test` passe sans erreur
- [ ] Workflow GitHub Actions passe complètement

### **Phase 1 (Stabilité)**
- [ ] R1.5 terminée (documentation)
- [ ] R1.6 terminée (gestion erreurs caméra)
- [ ] Phase 1 à 100%

### **Phase 2 (Qualité)**
- [x] Codecov configuré et fonctionnel
- [ ] Image Docker publiée (INF.2 : secrets DOCKER_HUB_* requis)
- [x] 80% de couverture de code (81 % local, PR #11–#15)
- [x] Tous les problèmes de linting corrigés (PR #9)

---

## 📚 **RESSOURCES**

- [ROADMAP.md](ROADMAP.md) - Feuille de route officielle
- [TODO.md](TODO.md) - Tâches en cours et problèmes connus
- [PROGRESS.md](PROGRESS.md) - Suivi des progrès
- [CONTRIBUTING.md](CONTRIBUTING.md) - Guide de contribution
- [Makefile](Makefile) - Commandes utiles
- [.github/workflows/](.github/workflows/) - Workflows CI/CD

---

## 💡 **RECOMMANDATIONS**

1. **Prioriser la Phase 0** : Sans une CI fonctionnelle, il est difficile de garantir la qualité du code.
2. **Corriger les problèmes de linting** : Même si ce sont des tests, un code clean est plus maintenable.
3. **Configurer Codecov tôt** : Cela permettra de suivre les progrès en couverture.
4. **Publier l'image Docker** : Cela facilitera grandement le déploiement pour les utilisateurs.
5. **Documenter les limites CC2** : C'est important pour éviter la frustration des utilisateurs.

---

*Ce document est généré automatiquement et doit être mis à jour régulièrement.*
