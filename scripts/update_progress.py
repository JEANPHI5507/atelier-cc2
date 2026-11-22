#!/usr/bin/env python3
"""4D6 Script pour mettre à jour automatiquement le fichier PROGRESS.md.

Utilisation:
    python scripts/update_progress.py --token VOTRE_GITHUB_TOKEN
    python scripts/update_progress.py --dry-run

Options:
    --token : Token GitHub personnel (nécessaire pour récupérer les issues)
    --dry-run : Mode simulation (affiche ce qui serait fait)
    --output : Fichier de sortie (par défaut: PROGRESS.md)
"""

import argparse
import re
import sys
from datetime import datetime
from typing import Optional

import httpx

# 4C4 Configuration
REPO_OWNER = "JEANPHI5507"
REPO_NAME = "atelier-cc2"
ROADMAP_FILE = "ROADMAP.md"
PROGRESS_FILE = "PROGRESS.md"


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

    async def get_issues(self, state: str = "all", labels: str = None) -> list[dict]:
        """Récupère toutes les issues du dépôt."""
        params = {"state": state, "per_page": 100}
        if labels:
            params["labels"] = labels

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/issues",
                headers=self.headers,
                params=params,
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des issues: {response.status_code}")
                return []
            return response.json()

    async def get_milestones(self) -> list[dict]:
        """Récupère tous les milestones du dépôt."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/milestones",
                headers=self.headers,
                params={"state": "all"},
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des milestones: {response.status_code}")
                return []
            return response.json()

    async def get_pull_requests(self, state: str = "all") -> list[dict]:
        """Récupère toutes les PR du dépôt."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/pulls",
                headers=self.headers,
                params={"state": state, "per_page": 100},
            )
            if response.status_code != 200:
                print(f"534 Erreur lors de la récupération des PR: {response.status_code}")
                return []
            return response.json()


def parse_roadmap(roadmap_content: str) -> dict:
    """Parse le fichier ROADMAP.md pour extraire les tâches organisées par phase."""
    phases = {}
    current_phase = None
    current_description = ""
    current_due_on = ""
    current_tasks = []

    lines = roadmap_content.split("\n")
    for line in lines:
        # Détection des phases
        phase_match = re.match(r"^### (⚡|🎨|🚀|🌍) (Phase \d+): (.+)$", line)
        if phase_match:
            if current_phase:
                phases[current_phase] = {
                    "title": current_phase,
                    "description": current_description,
                    "due_on": current_due_on,
                    "tasks": current_tasks,
                }
            current_phase = f"{phase_match.group(2)} {phase_match.group(3)}"
            current_description = phase_match.group(3)
            current_due_on = ""
            current_tasks = []
            continue

        # Détection de la date d'échéance
        due_match = re.match(r"^\| **Échéance** \| (.+?)\s*\|", line)
        if due_match:
            current_due_on = due_match.group(1)
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

            current_tasks.append(
                {
                    "id": task_id,
                    "title": title,
                    "description": description,
                    "complexity": complexity,
                    "status": status,
                }
            )
            continue

    # Ajouter la dernière phase
    if current_phase:
        phases[current_phase] = {
            "title": current_phase,
            "description": current_description,
            "due_on": current_due_on,
            "tasks": current_tasks,
        }

    return phases


def get_phase_number(phase_title: str) -> int:
    """Extrait le numéro de la phase."""
    match = re.search(r"Phase (\d+)", phase_title)
    if match:
        return int(match.group(1))
    return 0


def generate_progress_markdown(
    phases: dict,
    issues: list[dict] = None,
    pull_requests: list[dict] = None,
    milestones: list[dict] = None,  # noqa: ARG001
) -> str:
    """Génère le contenu du fichier PROGRESS.md."""
    now = datetime.now().strftime("%d %B %Y")

    # Compter les statistiques
    total_tasks = 0
    completed_tasks = 0
    in_progress_tasks = 0
    blocked_tasks = 0

    phase_stats = {}

    for phase_name, phase_data in phases.items():
        phase_tasks = phase_data["tasks"]
        total_tasks += len(phase_tasks)

        phase_completed = 0
        phase_in_progress = 0
        phase_to_do = 0

        for task in phase_tasks:
            if task["status"] == "✅ Terminée" or task["status"] == "Terminée":
                phase_completed += 1
                completed_tasks += 1
            elif task["status"] == "🟡 En Cours" or task["status"] == "En Cours":
                phase_in_progress += 1
                in_progress_tasks += 1
            elif task["status"] == "🔴 Bloquée" or task["status"] == "Bloquée":
                blocked_tasks += 1
            else:
                phase_to_do += 1

        phase_stats[phase_name] = {
            "total": len(phase_tasks),
            "completed": phase_completed,
            "in_progress": phase_in_progress,
            "to_do": phase_to_do,
        }

    # Calculer les pourcentages
    completion_rate = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

    markdown = f"""# 4CA527 Suivi des Progrès - Atelier CC2

> *Dernière mise à jour : {now}*
> *Ce fichier suit l'avancement des tâches de la [ROADMAP.md](ROADMAP.md).*


## 4CD **Sommaire**
1. [Statistiques Globales](#statistiques-globales)
2. [Progrès par Phase](#progrs-par-phase)
3. [Tâches en Cours](#tches-en-cours)
4. [Tâches Terminées](#tches-termines)
5. [Tâches Bloquées](#tches-bloques)
6. [Contributeurs Actifs](#contributeurs-actifs)
7. [Prochaines Étapes](#prochaines-tapes)


## 4C8 **Statistiques Globales**

| Métrique | Valeur | % Completion |
|----------|--------|--------------|
| **Tâches Totales** | {total_tasks} | - |
| **Tâches Terminées** | {completed_tasks} | {completion_rate:.1f}% |
| **Tâches en Cours** | {in_progress_tasks} | - |
| **Tâches à Faire** | {total_tasks - completed_tasks - in_progress_tasks - blocked_tasks} | - |
| **Tâches Bloquées** | {blocked_tasks} | - |

| Phase | Tâches | Terminées | En Cours | % Completion |
|-------|--------|-----------|----------|--------------|
"""

    for phase_name, stats in phase_stats.items():
        phase_number = get_phase_number(phase_name)
        priority_emoji = "🔴" if phase_number == 1 else "🟡" if phase_number <= 4 else "🟢"
        phase_completion = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        markdown += f"| **{phase_name}** | {stats['total']} | {stats['completed']} | {stats['in_progress']} | {phase_completion:.1f}% |\n"

    markdown += "\n---\n\n## 4CA **Progrès par Phase**\n\n"

    # Générer les sections par phase
    for phase_name, phase_data in phases.items():
        phase_number = get_phase_number(phase_name)
        priority_emoji = "🔴" if phase_number == 1 else "🟡" if phase_number <= 4 else "🟢"
        priority_text = (
            "Haute" if phase_number == 1 else "Moyenne" if phase_number <= 4 else "Faible"
        )

        stats = phase_stats[phase_name]
        phase_completion = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0

        status_emoji = "🟢" if phase_completion == 100 else "🟡" if phase_completion > 0 else "🔴"
        status_text = (
            "Terminée"
            if phase_completion == 100
            else "En Cours" if phase_completion > 0 else "À venir"
        )

        markdown += f"### {priority_emoji} **{phase_name}** *({priority_text} Priorité)*\n"
        markdown += f"**Objectif** : {phase_data['description']}\n"
        markdown += f"**Échéance** : {phase_data['due_on']}\n"
        markdown += f"**Statut** : {status_emoji} **{status_text}** ({stats['completed']}/{stats['total']} tâches terminées)\n\n"

        markdown += "| ID | Tâche | Statut | Contributeur | PR | Date Début | Date Fin |\n"
        markdown += "|----|-------|--------|--------------|----|------------|----------|\n"

        for task in phase_data["tasks"]:
            status_emoji = (
                "✅"
                if task["status"] == "✅ Terminée" or task["status"] == "Terminée"
                else (
                    "🟡"
                    if task["status"] == "🟡 En Cours" or task["status"] == "En Cours"
                    else (
                        "🔴"
                        if task["status"] == "🔴 Bloquée" or task["status"] == "Bloquée"
                        else "🟢"
                    )
                )
            )
            status_text = task["status"].replace("✅ ", "").replace("🟡 ", "").replace("🔴 ", "")
            markdown += f"| {task['id']} | {task['title']} | {status_emoji} {status_text} | - | - | - | - |\n"

        markdown += "\n"

    # Ajouter les sections restantes
    markdown += """---


## 469 **Tâches en Cours**
"""

    if in_progress_tasks > 0:
        markdown += "*Les tâches en cours seront listées ici automatiquement.*\n\n"
    else:
        markdown += "*Aucune tâche en cours pour le moment.*\n\n"

    markdown += """---

## 527 **Tâches Terminées**
"""

    if completed_tasks > 0:
        markdown += "*Les tâches terminées seront listées ici automatiquement.*\n\n"
    else:
        markdown += "*Aucune tâche terminée pour le moment.*\n\n"

    markdown += """---

## 534 **Tâches Bloquées**
"""

    if blocked_tasks > 0:
        markdown += "*Les tâches bloquées seront listées ici automatiquement.*\n\n"
    else:
        markdown += "*Aucune tâche bloquée pour le moment.*\n\n"

    markdown += """---

## 469 **Contributeurs Actifs**

| Contributeur | Tâches Assignées | PR Ouvertes | PR Mergées | Dernière Contribution |
|--------------|------------------|-------------|------------|----------------------|
"""

    if issues or pull_requests:
        # Extraire les contributeurs uniques
        contributors = set()
        if issues:
            for issue in issues:
                if issue.get("assignee"):
                    contributors.add(issue["assignee"]["login"])
        if pull_requests:
            for pr in pull_requests:
                if pr.get("user"):
                    contributors.add(pr["user"]["login"])

        if contributors:
            for contributor in sorted(contributors):
                markdown += f"| {contributor} | - | - | - | - |\n"
        else:
            markdown += "| - | - | - | - | - |\n"
    else:
        markdown += "| - | - | - | - | - |\n"

    markdown += """\n---

## 4CA **Prochaines Étapes**

### 4A1 **Pour la Communauté**
1. **Choisissez une tâche** dans la [ROADMAP.md](ROADMAP.md) ou ce fichier.
2. **Assignez-vous** à une tâche en commentant sur l'issue correspondante.
3. **Fork le dépôt** et commencez à développer.
4. **Ouvrez une PR** avec vos changements.

### 4BB **Pour les Mainteneurs**
1. **Revoir les PR ouvertes** et donner des retours.
2. **Mettre à jour ce fichier** régulièrement.
3. **Créer des milestones GitHub** pour chaque phase.
4. **Organiser des réunions de synchronisation** si nécessaire.


## 4CD **Comment Mettre à Jour ce Fichier**

### 469 **Manuellement**
1. Modifiez ce fichier directement.
2. Mettez à jour les statuts des tâches.
3. Commitez et poussez vos changements.

### 4BB **Automatiquement**
Utilisez le script `scripts/update_progress.py` :
```bash
python scripts/update_progress.py --token VOTRE_GITHUB_TOKEN
```


## 49A **Ressources Utiles**
- [ROADMAP.md](ROADMAP.md) - Feuille de route détaillée
- [CONTRIBUTING.md](CONTRIBUTING.md) - Guide de contribution
- [Guide de Développement](guide/developpement.md) - Documentation technique
- [Dépôt GitHub](https://github.com/JEANPHI5507/atelier-cc2) - Code source


## 3F3 **Licence**
Ce fichier est sous licence **MIT** (comme le reste du projet).


*Ce fichier est généré et maintenu par la communauté Atelier CC2. 64F*
"""

    return markdown


async def main():
    parser = argparse.ArgumentParser(description="Mettre à jour le fichier PROGRESS.md")
    parser.add_argument("--token", type=str, help="Token GitHub personnel")
    parser.add_argument("--dry-run", action="store_true", help="Mode simulation")
    parser.add_argument("--output", type=str, default=PROGRESS_FILE, help="Fichier de sortie")
    args = parser.parse_args()

    # Lire le fichier ROADMAP
    try:
        with open(ROADMAP_FILE, encoding="utf-8") as f:
            roadmap_content = f.read()
    except FileNotFoundError:
        print(f"534 Erreur: Fichier {ROADMAP_FILE} introuvable")
        sys.exit(1)

    # Parser les phases et tâches
    phases = parse_roadmap(roadmap_content)
    print(f"4A1 Trouvé {len(phases)} phases dans la ROADMAP")

    total_tasks = sum(len(phase["tasks"]) for phase in phases.values())
    print(f"4A1 Total des tâches: {total_tasks}")

    # Récupérer les données GitHub si token fourni
    issues = []
    pull_requests = []
    milestones = []

    if args.token:
        github = GitHubAPI(args.token)
        issues = await github.get_issues()
        pull_requests = await github.get_pull_requests()
        milestones = await github.get_milestones()
        print(
            f"4A1 Récupéré {len(issues)} issues, {len(pull_requests)} PR, {len(milestones)} milestones"
        )

    # Générer le markdown
    markdown = generate_progress_markdown(phases, issues, pull_requests, milestones)

    # Écrire le fichier
    if args.dry_run:
        print("\n4E2 [DRY RUN] Contenu généré (non écrit) :")
        print("-" * 50)
        print(markdown[:1000] + "..." if len(markdown) > 1000 else markdown)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"\n527 Fichier {args.output} mis à jour avec succès !")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
