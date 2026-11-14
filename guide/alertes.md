# Alertes

[← Retour au README](../README.fr.md) · 🇬🇧 [English](en/alerts.md)

L'atelier surveille l'imprimante **même quand aucune page n'est ouverte** : il suffit qu'il tourne (en service, c'est
le cas en permanence). Chaque événement est noté dans le journal (la cloche en haut de l'atelier).

## Ce qui est signalé

| Alerte | Quand |
|---|---|
| Impression lancée / reprise | au départ, après une pause |
| Impression en pause | pause demandée, ou par l'imprimante |
| **Plus de filament** | bobine vide ou coupée, avec le geste à faire |
| **Impression terminée** | avec une photo de la caméra, et un bouton « Faire le bilan » |
| **Plateau froid : tu peux retirer la pièce** | après une fin d'impression, quand le plateau passe sous 35 °C |
| Impression arrêtée | arrêt avant la fin |
| **Erreur de l'imprimante** | avec l'explication du code d'erreur officiel et quoi faire |
| L'imprimante signale un problème | une anomalie pendant l'impression |
| **Imprimante injoignable** / de nouveau joignable | plus de nouvelles pendant une impression |
| Impression suspecte / **Raté détecté** | l'IA de la caméra a un doute / est sûre (pause automatique si activée) |
| Caméra figée | la caméra ne change plus d'image (un défaut connu de certains firmwares) |
| Bobine presque vide / nouvelle bobine / bobine remise | moins de 100 g restants, autre bobine détectée dans le CANVAS, bobine déjà vue remise avec son poids |
| Entretien à faire | une tâche du carnet d'entretien arrive à échéance |

## Sur une page ouverte

Sur l'atelier et la tablette : un message, un son et une vibration (désactivables). Sur un ordinateur, la
notification du système si tu l'autorises. La tablette rallume son écran en mode nuit pour une fin, un plateau froid
ou un problème.

## Sur le téléphone, même appli fermée : ntfy

Les notifications d'une page web ne passent pas quand l'appli est fermée. Pour ça, l'atelier envoie ses alertes
importantes (tout sauf les simples informations) à **[ntfy](https://ntfy.sh)**, un service de notifications libre.

**Attention** : le texte de l'alerte passe alors par Internet (par le serveur ntfy.sh, ou le tien si tu en héberges un).
Il ne contient que le nom de l'impression et l'événement, pas d'image.

1. Installe l'appli **ntfy** sur le téléphone (Android : Play Store ou F-Droid ; iPhone : App Store).
2. Dans l'atelier, ouvre la cloche, partie **Alertes sur le téléphone, appli fermée**, et clique **Activer** :
   l'atelier choisit un sujet difficile à deviner (du type `cc2-4f9a…`) et l'affiche.
3. **Ouvrir dans ntfy** (depuis le téléphone) abonne l'appli à ce sujet ; sinon, dans ntfy : **+** et saisis-le.
   Puis **Envoyer un test**.

À la main, c'est une ligne de `config.toml` (un serveur ntfy à toi marche aussi, toujours en `https://`) :

```toml
[alertes]
ntfy = "https://ntfy.sh/mon-sujet-difficile-a-deviner"
```

Les notifications ont un lien qui ouvre l'atelier, et celle de fin d'impression un bouton **Faire le bilan**. Le lien
utilise l'adresse Tailscale si elle existe (voir [Téléphone, tablette, hors de la maison](telephone-et-tablette.md)),
sinon l'adresse de la maison.

Le sujet est secret seulement par sa longueur : ne le partage pas. Pour couper : **Désactiver** dans la cloche.
