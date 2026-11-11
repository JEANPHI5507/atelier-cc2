# Dépannage

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/troubleshooting.md)

Premier réflexe : `uv run cc2 doctor`, puis le journal de l'atelier (`uv run cc2 service journal`, ou la console si tu
l'as lancé à la main).

## L'imprimante

| Problème | Quoi faire |
|---|---|
| « Imprimante injoignable » | allumée ? même réseau que l'atelier ? `ping <IP>`. L'IP a peut-être changé : fixe-la dans la box. |
| Code d'accès refusé | relis-le sur l'écran (Paramètres → Réseau) ; il change après une réinitialisation. |
| Connexion refusée alors que tout est bon | le mode « LAN Only » est-il activé ? |
| « Réglage refusé sur le réseau local » | normal pour certaines commandes (origine, température…) : fais-le sur l'écran. |
| Le CANVAS ne montre pas mes bobines | les bobines doivent être préchargées ou chargées ; vérifie sur l'écran. |

## Le tranchage

| Problème | Quoi faire |
|---|---|
| « Slicer introuvable » | `make slicer` |
| « missing host OpenGL runtime library » | serveur sans écran : installe les bibliothèques de [l'installation](installation.md#sur-un-serveur-sans-écran). |
| « une partie flotterait sans support » | l'atelier réessaie avec des supports en arbre ; sinon choisis une autre pose. |
| « Unsupported 3MF version » | l'atelier réécrit les 3MF récents ; si ça persiste, exporte en STL ou 3MF depuis ton logiciel. |
| Trop de changements de couleur | « Simplifier les couleurs », couches de 0,24 mm, ou regrouper deux couleurs proches. |
| Plus grand que le plateau | baisse la hauteur, ou active « Découper en pièces ». |

## L'impression

| Problème | Quoi faire |
|---|---|
| Couleurs marbrées (une couleur traîne dans l'autre) | la purge ne suffit pas : mode Équilibré ou Qualité, et signale-le dans le bilan. |
| Gouttes aux changements de couleur | mode Équilibré : la buse s'essuie sur une tour avant de revenir sur la pièce. |
| **Tour de purge tombée** | mets en pause, retire la tour, **ne la remets pas**, reprends : quelques fils tomberont à sa place. |
| Pièce décollée, coins relevés | plateau à laver (eau chaude, liquide vaisselle, rinçage, sans toucher la surface) ; bordure dans le bilan. |
| L'IA crie aux spaghettis à tort | baisse la sensibilité (carte « Surveillance par caméra ») ; elle se tait d'elle-même à 98 %. |
| « Il semble rester quelque chose sur le plateau » | retire la pièce, ou « Le plateau est vide » si c'est une ombre ou un reflet. |

## Le téléphone et la tablette

| Problème | Quoi faire |
|---|---|
| Alerte de sécurité dans le navigateur | le certificat de l'atelier n'est pas installé (ou pas « approuvé » sur iPhone) : [guide](telephone-et-tablette.md). |
| Rien ne s'ouvre depuis le téléphone | l'atelier tourne-t-il avec `--reseau` ? même Wi-Fi ? l'adresse est affichée au lancement. |
| Code d'accès oublié | `uv run cc2 code-acces` en donne un nouveau. |
| « Trop d'essais » | 5 erreurs : attends 5 minutes. |
| Hors de la maison, ça ne marche pas | Tailscale actif sur le téléphone et sur la machine ? utilise l'adresse `…ts.net` affichée au lancement. |
| La caméra ne s'affiche pas | lumière de l'imprimante éteinte (bouton « Allumer » sur l'image) ; sinon caméra figée : éteins et rallume l'imprimante. |
| Pas de notification appli fermée | ntfy est-il activé (cloche) et l'appli ntfy abonnée au sujet ? « Envoyer un test ». |

## ComfyUI

| Problème | Quoi faire |
|---|---|
| `cc2 doctor` : ComfyUI injoignable | ComfyUI lancé ? avec `--listen 0.0.0.0` s'il est sur une autre machine ? bonne adresse dans `[comfyui] url` ? |
| « value not in list » | un fichier de modèle manque ou porte un autre nom : [liste des fichiers](comfyui.md#2-télécharger-les-modèles). |
| Mémoire vidéo insuffisante | ferme les autres logiciels qui utilisent la carte ; essaie `trellis_texte_vers_3d_rapide`. |
| Le modèle 3D est mauvais | pars d'une image propre (objet seul, fond uni), ou passe par `photo_vers_figurine_3d`. |
