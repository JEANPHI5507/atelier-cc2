#!/usr/bin/env python3
"""4D6 Script pour créer automatiquement les issues GitHub à partir de la ROADMAP.

Utilisation:
    python scripts/create_issues.py --token VOTRE_GITHUB_TOKEN --dry-run
    python scripts/create_issues.py --token VOTRE_GITHUB_TOKEN

Options:
    --token : Token GitHub personnel (nécessaire pour créer des issues)
    --dry-run : Mode simulation (affiche ce qui serait fait sans créer les issues)
    --repo : Nom du dépôt (format: owner/repo, par défaut: JEANPHI5507/atelier-cc2)
"""

import argparse
import json
import re
import sys
from typing import Optional

import httpx

# 4C4 Configuration
REPO_OWNER = "JEANPHI5507"
REPO_NAME = "atelier-cc2"
ROADMAP_FILE = "ROADMAP.md"


# 4DD Mappings pour les labels et milestones
PHASE_TO_MILESTONE = {
    "Phase 1": "Phase 1: Stabilité & Portabilité",
    "Phase 2": "Phase 2: Expérience Utilisateur",
    "Phase 3": "Phase 3: Fonctionnalités Avancées",
    "Phase 4": "Phase 4: Performance & Optimisation",
    "Phase 5": "Phase 5: Intégrations & Écosystème",
}

PRIORITY_TO_LABEL = {
    "🔴 Haute": "priorité:critique",
    "🟡 Moyenne": "priorité:haute",
    "🟢 Faible": "priorité:faible",
}

CATEGORY_TO_LABEL = {
    "Stabilité & Portabilité": "catégorie:stabilité",
    "Expérience Utilisateur": "catégorie:ux",
    "Fonctionnalités Avancées": "catégorie:fonctionnalité",
    "Performance & Optimisation": "catégorie:performance",
    "Intégrations & Écosystème": "catégorie:intégration",
}


class GitHubAPI:
    """Client simple pour l'API GitHub."""

    def __init__(self, token: str, repo_owner: str = REPO_OWNER, repo_name: str = REPO_NAME):
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_milestone(self, title: str) -> dict | None:
        """Récupère un milestone par son titre."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/milestones",
                headers=self.headers,
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des milestones: {response.status_code}")
                return None

            milestones = response.json()
            for milestone in milestones:
                if milestone["title"] == title:
                    return milestone
            return None

    async def create_milestone(self, title: str, description: str, due_on: str) -> dict:
        """Crée un nouveau milestone."""
        data = {
            "title": title,
            "description": description,
            "due_on": due_on,
            "state": "open",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/milestones",
                headers=self.headers,
                json=data,
            )
            if response.status_code != 201:
                print(f"534 Erreur lors de la création du milestone: {response.status_code}")
                print(response.text)
                return {}
            return response.json()

    async def get_label(self, name: str) -> dict | None:
        """Récupère un label par son nom."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/labels",
                headers=self.headers,
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des labels: {response.status_code}")
                return None

            labels = response.json()
            for label in labels:
                if label["name"] == name:
                    return label
            return None

    async def create_label(self, name: str, color: str, description: str = "") -> dict:
        """Crée un nouveau label."""
        data = {
            "name": name,
            "color": color,
            "description": description,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/labels",
                headers=self.headers,
                json=data,
            )
            if response.status_code != 201:
                print(f"534 Erreur lors de la création du label: {response.status_code}")
                print(response.text)
                return {}
            return response.json()

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] = None,
        milestone: int = None,
    ) -> dict:
        """Crée une nouvelle issue."""
        data = {
            "title": title,
            "body": body,
            "labels": labels or [],
        }
        if milestone:
            data["milestone"] = milestone

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/issues",
                headers=self.headers,
                json=data,
            )
            if response.status_code != 201:
                print(f"534 Erreur lors de la création de l'issue: {response.status_code}")
                print(response.text)
                return {}
            return response.json()

    async def get_issue_by_title(self, title: str) -> dict | None:
        """Récupère une issue par son titre."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/issues",
                headers=self.headers,
                params={"state": "all", "per_page": 100},
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des issues: {response.status_code}")
                return None

            issues = response.json()
            for issue in issues:
                if issue["title"] == title:
                    return issue
            return None


def parse_roadmap(roadmap_content: str) -> list[dict]:
    """Parse le fichier ROADMAP.md pour extraire les tâches."""
    tasks = []
    current_phase = None
    current_category = None

    lines = roadmap_content.split("\n")
    for line in lines:
        # Détection des phases
        phase_match = re.match(r"^### (⚡|🎨|🚀|⚡|🌍) (Phase \d+): (.+)$", line)
        if phase_match:
            current_phase = f"{phase_match.group(2)} {phase_match.group(3)}"
            current_category = current_phase
            continue

        # Détection des backlog
        if line.startswith(("### 📋 **Backlog", "## 📋 **Backlog")):
            current_phase = "Backlog"
            current_category = current_phase
            continue

        # Détection des en-têtes de tableau
        if line.startswith("| ID | Tâche |"):
            continue

        # Détection des lignes de tâche
        task_match = re.match(
            r"^\| (R\d+\.\d+) \| (.+?) \| (.+?) \| (⭐+)\s*\| (.+?) \|",
            line,
        )
        if task_match:
            task_id = task_match.group(1)
            title = task_match.group(2).strip()
            description = task_match.group(3).strip()
            complexity = task_match.group(4).count("⭐")
            status = task_match.group(5).strip()

            # Extraire les emojis de priorité
            priority = "🟢 Faible"
            if "🔴" in line:
                priority = "🔴 Haute"
            elif "🟡" in line:
                priority = "🟡 Moyenne"

            tasks.append(
                {
                    "id": task_id,
                    "title": title,
                    "description": description,
                    "complexity": complexity,
                    "status": status,
                    "priority": priority,
                    "phase": current_phase,
                    "category": current_category,
                }
            )
            continue

    return tasks


def generate_issue_body(task: dict) -> str:
    """Génère le corps d'une issue à partir d'une tâche."""
    body = f"""## 4A1 {task['title']}

**ID** : {task['id']}
**Phase** : {task['phase']}
**Priorité** : {task['priority']}
**Complexité** : {'⭐' * task['complexity']}


### 4F0 Description
{task['description']}


### 527 Étapes à Suivre
- [ ] Comprendre la tâche et son contexte
- [ ] Implémenter la solution
- [ ] Ajouter des tests unitaires
- [ ] Mettre à jour la documentation si nécessaire
- [ ] Vérifier que tous les tests passent (`make test`)
- [ ] Ouvrir une PR avec une description claire


### 4CD Ressources Utiles
- [ROADMAP.md](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/main/ROADMAP.md)
- [CONTRIBUTING.md](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/main/CONTRIBUTING.md)
- [Guide de Développement](https://github.com/{REPO_OWNER}/{REPO_NAME}/blob/main/guide/developpement.md)


*Merci pour votre contribution ! 64F*
"""
    return body


def get_labels_for_task(task: dict) -> list[str]:
    """Détermine les labels pour une tâche."""
    labels = []

    # Label de priorité
    priority_label = PRIORITY_TO_LABEL.get(task["priority"], "priorité:moyenne")
    labels.append(priority_label)

    # Label de catégorie
    if task["phase"] and task["phase"] != "Backlog":
        for phase, _label in PHASE_TO_MILESTONE.items():
            if phase in task["phase"]:
                category = task["phase"].split(": ")[1] if ": " in task["phase"] else task["phase"]
                if category in CATEGORY_TO_LABEL:
                    labels.append(CATEGORY_TO_LABEL[category])
                break

    # Label de type
    if "Bug" in task["title"] or "bug" in task["title"].lower():
        labels.append("bug")
    elif "Nouvelle" in task["title"] or "Ajouter" in task["title"]:
        labels.append("enhancement")
    else:
        labels.append("triage")

    return labels


async def main():
    parser = argparse.ArgumentParser(description="Créer des issues GitHub à partir de la ROADMAP")
    parser.add_argument("--token", type=str, help="Token GitHub personnel")
    parser.add_argument("--dry-run", action="store_true", help="Mode simulation (pas de création)")
    parser.add_argument("--repo-owner", type=str, default=REPO_OWNER, help="Propriétaire du dépôt")
    parser.add_argument("--repo-name", type=str, default=REPO_NAME, help="Nom du dépôt")
    args = parser.parse_args()

    # Lire le fichier ROADMAP
    try:
        with open(ROADMAP_FILE, encoding="utf-8") as f:
            roadmap_content = f.read()
    except FileNotFoundError:
        print(f"534 Erreur: Fichier {ROADMAP_FILE} introuvable")
        sys.exit(1)

    # Parser les tâches
    tasks = parse_roadmap(roadmap_content)
    print(f"4A1 Trouvé {len(tasks)} tâches dans la ROADMAP")

    if not tasks:
        print("534 Aucune tâche trouvée dans la ROADMAP")
        sys.exit(1)

    # Filtrer les tâches déjà existantes (si token fourni)
    existing_issues = []
    if args.token:
        github = GitHubAPI(args.token, args.repo_owner, args.repo_name)
        for task in tasks:
            issue = await github.get_issue_by_title(task["title"])
            if issue:
                existing_issues.append(task["title"])
                print(f"535 Issue existante: {task['title']} (#{issue['number']})")

    # Créer les milestones si nécessaire
    milestones = {}
    if args.token:
        github = GitHubAPI(args.token, args.repo_owner, args.repo_name)
        for phase, title in PHASE_TO_MILESTONE.items():
            milestone = await github.get_milestone(title)
            if not milestone and not args.dry_run:
                print(f"4A1 Création du milestone: {title}")
                milestone = await github.create_milestone(
                    title=title,
                    description=f"Phase {phase.split()[1]}: {title}",
                    due_on="2025-12-31",  # Date par défaut
                )
                milestones[title] = milestone["number"]
            elif milestone:
                milestones[title] = milestone["number"]
                print(f"535 Milestone existant: {title} (#{milestone['number']})")

    # Créer les issues
    created_issues = []
    skipped_issues = []

    for task in tasks:
        if task["title"] in existing_issues:
            skipped_issues.append(task["title"])
            continue

        labels = get_labels_for_task(task)
        body = generate_issue_body(task)

        # Déterminer le milestone
        milestone_number = None
        if task["phase"] in PHASE_TO_MILESTONE:
            milestone_title = PHASE_TO_MILESTONE[task["phase"]]
            if milestone_title in milestones:
                milestone_number = milestones[milestone_title]

        if args.dry_run:
            print("\n4E2 [DRY RUN] Créerait l'issue:")
            print(f"  Titre: {task['title']}")
            print(f"  Labels: {labels}")
            print(f"  Milestone: {milestone_number}")
            print(f"  Priorité: {task['priority']}")
            created_issues.append(task["title"])
        else:
            if not args.token:
                print(
                    f"\n4A1 Pour créer l'issue '{task['title']}', fournissez un token GitHub avec --token"
                )
                continue

            github = GitHubAPI(args.token, args.repo_owner, args.repo_name)
            issue = await github.create_issue(
                title=task["title"],
                body=body,
                labels=labels,
                milestone=milestone_number,
            )
            if issue:
                print(f"527 Issue créée: {task['title']} (#{issue['number']})")
                created_issues.append(task["title"])
            else:
                print(f"534 Échec de la création de l'issue: {task['title']}")

    # Résumé
    print("\n" + "=" * 50)
    print("4CA **Résumé**")
    print("=" * 50)
    print(f"527 Issues créées: {len(created_issues)}")
    print(f"535 Issues existantes (sautées): {len(skipped_issues)}")
    print(f"4A1 Total des tâches dans la ROADMAP: {len(tasks)}")

    if args.dry_run:
        print("\n4A1 *Mode dry-run: Aucune issue n'a été réellement créée*")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
