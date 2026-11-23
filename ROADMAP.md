# 9A83FC Atelier CC2 - Roadmap Officielle

> *Dernière mise à jour : 22 Novembre 2024*
> *Version : 0.2.0 (en développement)*
> *Statut : 4A17E2 **Phase 1 - Stabilité & Portabilité** (en cours)*

---

## 4CD 3F74CA **Sommaire**
1. [Vision du Projet](#vision-du-projet)
2. [Phases de Développement](#phases-de-dveloppement)
3. [Feuille de Route Détaillée](#feuille-de-route-dtaille)
   - [Phase 1 : Stabilité & Portabilité (🔴 Priorité Haute)](#phase-1-stabilit--portabilit-)
   - [Phase 2 : Expérience Utilisateur (🟡 Priorité Moyenne)](#phase-2-exprience-utilisateur-)
   - [Phase 3 : Fonctionnalités Avancées](#phase-3-fonctionnalits-avances)
   - [Phase 4 : Performance & Optimisation](#phase-4-performance--optimisation)
   - [Phase 5 : Intégrations & Écosystème](#phase-5-intgrations--cosystme)
4. [Backlog (Idées Futures)](#backlog-ides-futures)
5. [Comment Contribuer](#comment-contribuer)
6. [Suivi des Progrès](#suivi-des-progrs)

---

## 4C830D **Vision du Projet**

**Atelier CC2** vise à devenir **la plateforme de référence** pour l'impression 3D multicolore sur **Elegoo Centauri Carbon 2** (et à terme, d'autres imprimantes).

**Objectifs stratégiques :**
- 4A1 **Accessibilité** : Rendre l'impression multicolore accessible à tous (débutants comme experts).
- 527 **Fiabilité** : Zéro régression, compatibilité garantie avec les mises à jour firmware.
- 4BB **Extensibilité** : Architecture modulaire pour supporter de nouvelles imprimantes et fonctionnalités.
- 30E **Écosystème** : Intégration avec les outils existants (CAO, cloud, domotique).

---

## 52C4CD **Phases de Développement**

| Phase | Nom | Durée Estimée | Statut | Priorité | Livrables Principaux |
|-------|-----|----------------|--------|----------|----------------------|
| **1** | **Stabilité & Portabilité** | 1-2 mois | 4A1 **En Cours** | 534 **🔴 Haute** | Docker, WSL2, Mode Safe, Diagnostic amélioré |
| **2** | **Expérience Utilisateur** | 2-3 mois | 53D4CA **À venir** | 7E1 **🟡 Moyenne** | Mode Débutant, CANVAS 3D, Notifications intelligentes |
| **3** | **Fonctionnalités Avancées** | 3-4 mois | 53D4CA **À venir** | 7E1 **🟡 Moyenne** | Multi-imprimantes, Planification, Thingiverse |
| **4** | **Performance & Optimisation** | 2 mois | 53D4CA **À venir** | 7E1 **🟡 Moyenne** | Découpe incrémentale, Mode léger, Cache |
| **5** | **Intégrations & Écosystème** | 3-6 mois | 53D4CA **À venir** | 7E2 **🟢 Faible** | Home Assistant, OctoPrint, Let's Encrypt |

---

---

## 4D64CA **Feuille de Route Détaillée**

---

### 534 **⚡ Phase 1 : Stabilité & Portabilité** *(🔴 Priorité Haute)*
**Objectif** : Résoudre les problèmes critiques de compatibilité et de stabilité.

| ID | Tâche | Description | Complexité | Statut | Issue GitHub | PR | Contributeur |
|----|-------|-------------|------------|--------|--------------|----|--------------|
| **R1.1** | 489 **Dockerisation** | Créer une image Docker officielle avec toutes les dépendances (OrcaSlicer, IA, Python). | ⭐⭐⭐ | 53D4CA **Terminé** | - | [#1](https://github.com/JEANPHI5507/atelier-cc2/pull/1) | JEANPHI5507 |
| **R1.2** | 526 **Support WSL2** | Guide d'installation complet pour Windows via WSL2. | ⭐⭐ | 53D4CA **Terminé** | - | [#1](https://github.com/JEANPHI5507/atelier-cc2/pull/1) | JEANPHI5507 |
| **R1.3** | 9A8 **Mode Safe Firmware** | Désactiver les commandes critiques si le firmware n'est pas reconnu. | ⭐⭐⭐ | 53D4CA **Terminé** | - | [#1](https://github.com/JEANPHI5507/atelier-cc2/pull/1) | JEANPHI5507 |
| **R1.4** | 4A1 **Diagnostic Amélioré** | Étendre `cc2 doctor` pour vérifier OrcaSlicer, IA, caméra, etc. | ⭐⭐ | 53D4CA **Terminé** | - | [#1](https://github.com/JEANPHI5507/atelier-cc2/pull/1) | JEANPHI5507 |
| **R1.5** | 4DD **Documentation des Limites CC2** | Ajouter une section claire dans l'UI sur les commandes bloquées. | ⭐ | 53D4CA **Terminé** | [#6](https://github.com/JEANPHI5507/atelier-cc2/issues/6) | [#4](https://github.com/JEANPHI5507/atelier-cc2/pull/4) | Vibe Code |
| **R1.6** | 998 **Gestion des Erreurs Caméra** | Détection automatique des caméras gelées + redémarrage. | ⭐⭐ | 53D4CA **Terminé** | [#5](https://github.com/JEANPHI5507/atelier-cc2/issues/5) | [#7](https://github.com/JEANPHI5507/atelier-cc2/pull/7) | Vibe Code |

**Livrables Phase 1 :**
- [ ] Image Docker publique sur Docker Hub
- [x] Guide d'installation WSL2
- [x] Système de détection de firmware
- [x] Outil `cc2 doctor` étendu
- [x] Messages d'erreur clairs dans l'UI

---

### 7E1 **🎨 Phase 2 : Expérience Utilisateur** *(🟡 Priorité Moyenne)*
**Objectif** : Rendre l'outil accessible et intuitif pour tous les utilisateurs.

| ID | Tâche | Description | Complexité | Statut | Issue GitHub | PR | Contributeur |
|----|-------|-------------|------------|--------|--------------|----|--------------|
| **R2.1** | 466 **Mode Débutant** | Masquer les options avancées pour les nouveaux utilisateurs. | ⭐⭐⭐ | 53D4CA **À faire** | [#7](https://github.com/JEANPHI5507/atelier-cc2/issues/7) | - | - |
| **R2.2** | 3A8 **Visualisation CANVAS 3D** | Schéma interactif des 4 bobines avec couleurs actuelles. | ⭐⭐⭐ | 53D4CA **À faire** | [#8](https://github.com/JEANPHI5507/atelier-cc2/issues/8) | - | - |
| **R2.3** | 514 **Notifications Intelligentes** | Niveaux de priorité (Critique/Avertissement/Info) + historique. | ⭐⭐ | 53D4CA **À faire** | [#9](https://github.com/JEANPHI5507/atelier-cc2/issues/9) | - | - |
| **R2.4** | 4BE **Backup Automatique** | Sauvegarde de `config.toml` et bibliothèque avec versioning. | ⭐⭐ | 53D4CA **À faire** | [#10](https://github.com/JEANPHI5507/atelier-cc2/issues/10) | - | - |
| **R2.5** | 39F **Assistant Guidé** | Étendre le chat pour proposer des workflows pas à pas. | ⭐⭐⭐ | 53D4CA **À faire** | [#11](https://github.com/JEANPHI5507/atelier-cc2/issues/11) | - | - |
| **R2.6** | 4F9 **Tutoriels Intégrés** | Ajouter des GIFs/vidéos dans les tooltips et l'onglet Aide. | ⭐⭐ | 53D4CA **À faire** | [#12](https://github.com/JEANPHI5507/atelier-cc2/issues/12) | - | - |
| **R2.7** | 5C4 **Thème Sombre pour Tablette** | Meilleure lisibilité sur écrans OLED. | ⭐ | 53D4CA **À faire** | [#13](https://github.com/JEANPHI5507/atelier-cc2/issues/13) | - | - |
| **R2.8** | 421 **Accessibilité** | Raccourcis clavier, navigation au clavier, contraste WCAG. | ⭐⭐ | 53D4CA **À faire** | [#14](https://github.com/JEANPHI5507/atelier-cc2/issues/14) | - | - |

**Livrables Phase 2 :**
- [ ] Interface simplifiée pour les débutants
- [ ] Visualisation interactive du CANVAS
- [ ] Système de notifications amélioré
- [ ] Système de backup automatique
- [ ] Assistant guidé étendu
- [ ] Documentation visuelle intégrée

---

### 7E1 **🚀 Phase 3 : Fonctionnalités Avancées** *(🟡 Priorité Moyenne)*
**Objectif** : Ajouter des fonctionnalités demandées par la communauté.

| ID | Tâche | Description | Complexité | Statut | Issue GitHub | PR | Contributeur |
|----|-------|-------------|------------|--------|--------------|----|--------------|
| **R3.1** | 4BB **Gestion Multi-Imprimantes** | Sélecteur d'imprimante + configurations par imprimante. | ⭐⭐⭐ | 53D4CA **À faire** | [#15](https://github.com/JEANPHI5507/atelier-cc2/issues/15) | - | - |
| **R3.2** | 4C5 **Planification des Impressions** | Calendrier pour programmer des impressions + estimation du temps. | ⭐⭐⭐ | 53D4CA **À faire** | [#16](https://github.com/JEANPHI5507/atelier-cc2/issues/16) | - | - |
| **R3.3** | 4D3 **Intégration Thingiverse/Printables** | Import direct depuis les plateformes via API. | ⭐⭐⭐ | 53D4CA **À faire** | [#17](https://github.com/JEANPHI5507/atelier-cc2/issues/17) | - | - |
| **R3.4** | 4E2 **Partage de Profils** | Exporter/importer les profils (couleurs, découpe) en JSON. | ⭐⭐ | 53D4CA **À faire** | [#18](https://github.com/JEANPHI5507/atelier-cc2/issues/18) | - | - |
| **R3.5** | 4A7 **Support PrusaSlicer/Bambu Studio** | Alternative à OrcaSlicer pour plus de flexibilité. | ⭐⭐⭐⭐ | 53D4CA **À faire** | [#19](https://github.com/JEANPHI5507/atelier-cc2/issues/19) | - | - |
| **R3.6** | 4DD **Journal des Maintenance** | Historique des actions de maintenance (nettoyage, calibration). | ⭐⭐ | 53D4CA **À faire** | [#20](https://github.com/JEANPHI5507/atelier-cc2/issues/20) | - | - |
| **R3.7** | 4B8 **Vérification Niveau Filament** | Vérifier le niveau de filament avant de lancer une impression. | ⭐⭐ | 53D4CA **À faire** | [#21](https://github.com/JEANPHI5507/atelier-cc2/issues/21) | - | - |

**Livrables Phase 3 :**
- [ ] Support multi-imprimantes
- [ ] Planificateur d'impressions
- [ ] Intégration avec Thingiverse/Printables
- [ ] Système de partage de profils
- [ ] Support de plusieurs slicers

---

### 7E1 **⚡ Phase 4 : Performance & Optimisation** *(🟡 Priorité Moyenne)*
**Objectif** : Améliorer les performances et réduire la consommation de ressources.

| ID | Tâche | Description | Complexité | Statut | Issue GitHub | PR | Contributeur |
|----|-------|-------------|------------|--------|--------------|----|--------------|
| **R4.1** | 4A8 **Découpe Incrémentale** | Afficher une progression en temps réel avec estimation. | ⭐⭐⭐ | 53D4CA **À faire** | [#22](https://github.com/JEANPHI5507/atelier-cc2/issues/22) | - | - |
| **R4.2** | 4BD **Mode Léger (Raspberry Pi)** | Désactiver l'IA et la 3D en direct pour les machines légères. | ⭐⭐ | 53D4CA **À faire** | [#23](https://github.com/JEANPHI5507/atelier-cc2/issues/23) | - | - |
| **R4.3** | 4C1 **Cache des Modèles** | Ne pas re-découper si le modèle n'a pas changé. | ⭐⭐ | 53D4CA **À faire** | [#24](https://github.com/JEANPHI5507/atelier-cc2/issues/24) | - | - |
| **R4.4** | 4B0 **Optimisation Mémoire** | Réduire la taille des images (caméra, timelapse). | ⭐⭐ | 53D4CA **À faire** | [#25](https://github.com/JEANPHI5507/atelier-cc2/issues/25) | - | - |
| **R4.5** | 4C8 **Parallélisation de la Découpe** | Utiliser plusieurs cœurs CPU pour accélérer la découpe. | ⭐⭐⭐ | 53D4CA **À faire** | [#26](https://github.com/JEANPHI5507/atelier-cc2/issues/26) | - | - |
| **R4.6** | 4F6 **Flux Vidéo WebRTC** | Remplacer MQTT par WebRTC pour un flux caméra plus fluide. | ⭐⭐⭐ | 53D4CA **À faire** | [#27](https://github.com/JEANPHI5507/atelier-cc2/issues/27) | - | - |

**Livrables Phase 4 :**
- [ ] Découpe avec barre de progression
- [ ] Mode léger pour Raspberry Pi
- [ ] Système de cache des modèles
- [ ] Optimisation mémoire
- [ ] Flux vidéo optimisé

---

### 7E2 **🌍 Phase 5 : Intégrations & Écosystème** *(🟢 Priorité Faible)*
**Objectif** : Étendre l'écosystème et intégrer avec d'autres outils.

| ID | Tâche | Description | Complexité | Statut | Issue GitHub | PR | Contributeur |
|----|-------|-------------|------------|--------|--------------|----|--------------|
| **R5.1** | 4BB **Intégration Home Assistant** | Contrôler l'imprimante via Home Assistant (MQTT/API REST). | ⭐⭐⭐ | 53D4CA **À faire** | [#28](https://github.com/JEANPHI5507/atelier-cc2/issues/28) | - | - |
| **R5.2** | 41B **Plugin OctoPrint** | Permettre de contrôler la CC2 via OctoPrint. | ⭐⭐⭐⭐ | 53D4CA **À faire** | [#29](https://github.com/JEANPHI5507/atelier-cc2/issues/29) | - | - |
| **R5.3** | 513 **Let's Encrypt** | Certificats HTTPS valides automatiquement. | ⭐⭐ | 53D4CA **À faire** | [#30](https://github.com/JEANPHI5507/atelier-cc2/issues/30) | - | - |
| **R5.4** | 4E6 **Webhooks Discord/Slack** | Envoyer des alertes sur Discord/Slack. | ⭐⭐ | 53D4CA **À faire** | [#31](https://github.com/JEANPHI5507/atelier-cc2/issues/31) | - | - |
| **R5.5** | 4CC **Intégration Git** | Versionner les fichiers 3D avec Git. | ⭐⭐⭐ | 53D4CA **À faire** | [#32](https://github.com/JEANPHI5507/atelier-cc2/issues/32) | - | - |
| **R5.6** | 418 **Support Centauri Carbon 1** | Tester et ajouter des profils pour la CC1. | ⭐⭐⭐ | 53D4CA **À faire** | [#33](https://github.com/JEANPHI5507/atelier-cc2/issues/33) | - | - |
| **R5.7** | 4BE **Marketplace de Modèles** | Plateforme pour partager des modèles 3D multicolores. | ⭐⭐⭐⭐⭐ | 53D4CA **À faire** | [#34](https://github.com/JEANPHI5507/atelier-cc2/issues/34) | - | - |

**Livrables Phase 5 :**
- [ ] Intégration Home Assistant
- [ ] Plugin OctoPrint
- [ ] Certificats Let's Encrypt
- [ ] Webhooks pour Discord/Slack
- [ ] Support de la Centauri Carbon 1

---

---

## 4D44CA **Backlog (Idées Futures)**

| ID | Idée | Description | Complexité | Priorité | Statut |
|----|------|-------------|------------|----------|--------|
| **B1** | 9E0 **IA de Réparation Automatique** | Détecter et réparer les modèles avant découpe. | ⭐⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B2** | 4B8 **Génération de Supports Intelligents** | IA pour générer des supports optimisés. | ⭐⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B3** | 468 **Mode "École"** | Version simplifiée pour les cours/ateliers. | ⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B4** | 4BB **Système de Plugins** | Architecture modulaire pour ajouter des fonctionnalités. | ⭐⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B5** | 4C6 **Intégration Blender** | Plugin pour exporter directement vers Atelier CC2. | ⭐⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B6** | 4A1 **2FA pour l'UI** | Authentification à 2 facteurs. | ⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B7** | 4B0 **Mode CPU pour ComfyUI** | Génération IA sans GPU (lent mais fonctionnel). | ⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |
| **B8** | 30E **Cloud IA (Replicate)** | Option pour utiliser des services externes. | ⭐⭐⭐⭐ | 7E2 Faible | 53D4CA **Backlog** |

---

---

## 4D64CA **Comment Contribuer**

### 469 **Pour les Développeurs**
1. **Choisissez une tâche** dans la roadmap (priorité haute ou moyenne recommandée).
2. **Vérifiez les dépendances** :
   - Lisez le [CONTRIBUTING.md](CONTRIBUTING.md) pour les bonnes pratiques.
   - Consultez le [guide de développement](guide/developpement.md).
3. **Créez une branche** :
   ```bash
   git checkout -b feature/nom-de-la-fonctionnalite
   ```
4. **Ouvrez une Issue** (si elle n'existe pas) :
   - Utilisez les [templates d'issues](#) pour décrire votre contribution.
5. **Développez et testez** :
   - Exécutez `make test` pour vérifier que tout fonctionne.
   - Ajoutez des tests unitaires si nécessaire.
6. **Ouvrez une PR** :
   - Utilisez le [template de PR](#) pour décrire vos changements.
   - Liez votre PR à l'issue correspondante.

### 468 **Pour les Non-Développeurs**
- **Testez les nouvelles fonctionnalités** et signalez les bugs.
- **Améliorez la documentation** (traductions, guides, FAQ).
- **Partagez vos retours** via les issues GitHub.
- **Contribuez aux designs** (maquettes, icônes, etc.).

### 4B0 **Bonnes Pratiques**
- 527 **Tests** : Tout nouveau code doit être couvert par des tests.
- 4DD **Documentation** : Mettez à jour les guides et le README si nécessaire.
- 440 **Revue de Code** : Attendez les retours avant de merger.
- 507 **Compatibilité** : Vérifiez que votre code fonctionne avec le simulateur.
- 44B **Commits** : Messages clairs et atomiques (1 commit = 1 changement logique).

---

---

## 4CA4CD **Suivi des Progrès**

### 4C8 **Tableau de Bord**
| Phase | Tâches Totales | Tâches Terminées | % Completion | Statut |
|-------|----------------|------------------|--------------|--------|
| **Phase 1** | 6 | 0 | 0% | 534 **En Cours** |
| **Phase 2** | 8 | 0 | 0% | 53D4CA **À venir** |
| **Phase 3** | 7 | 0 | 0% | 53D4CA **À venir** |
| **Phase 4** | 6 | 0 | 0% | 53D4CA **À venir** |
| **Phase 5** | 7 | 0 | 0% | 53D4CA **À venir** |
| **Backlog** | 8 | 0 | 0% | 53D4CA **En attente** |

### 4C5 **Calendrier Prévisionnel**
| Phase | Début Prévu | Fin Prévue | Statut |
|-------|--------------|------------|--------|
| **Phase 1** | Novembre 2024 | Décembre 2024 | 4A1 **En Cours** |
| **Phase 2** | Janvier 2025 | Mars 2025 | 53D4CA **À venir** |
| **Phase 3** | Avril 2025 | Juin 2025 | 53D4CA **À venir** |
| **Phase 4** | Juillet 2025 | Août 2025 | 53D4CA **À venir** |
| **Phase 5** | Septembre 2025 | Décembre 2025 | 53D4CA **À venir** |

---

### 4CC **Milestones GitHub**
Les milestones suivantes ont été créées pour suivre les progrès :
- [Milestone Phase 1: Stabilité & Portabilité](https://github.com/JEANPHI5507/atelier-cc2/milestone/1)
- [Milestone Phase 2: Expérience Utilisateur](https://github.com/JEANPHI5507/atelier-cc2/milestone/2)
- [Milestone Phase 3: Fonctionnalités Avancées](https://github.com/JEANPHI5507/atelier-cc2/milestone/3)
- [Milestone Phase 4: Performance & Optimisation](https://github.com/JEANPHI5507/atelier-cc2/milestone/4)
- [Milestone Phase 5: Intégrations & Écosystème](https://github.com/JEANPHI5507/atelier-cc2/milestone/5)

---

---

## 49A **Licence**
Ce fichier est sous licence **MIT** (comme le reste du projet).

---

## 489 **Remerciements**
Merci à tous les contributeurs qui rendent ce projet possible !

- 469 **Développeurs** : [JEANPHI5507](https://github.com/JEANPHI5507) (mainteneur principal)
- 468 **Testeurs** : Communauté Atelier CC2
- 4DD **Documentation** : Contributeurs des guides

---

*4A1 Ce document est généré automatiquement. Pour les mises à jour, consultez le dépôt GitHub.*
