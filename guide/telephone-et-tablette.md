# Téléphone, tablette, hors de la maison

[← Retour au README](../README.md)

## Ouvrir l'atelier au réseau de la maison

```bash
uv run cc2 --control dash --reseau
```

(Le service installé par `cc2 --control service installer` le fait déjà.)

L'atelier s'ouvre alors aux autres appareils du réseau, **en HTTPS sur le port 8443**, protégé par un **code
d'accès**. Il s'installe sur le téléphone comme une appli : icône sur l'écran d'accueil, plein écran, et un message
clair si la machine de l'atelier est éteinte. Au lancement, la console affiche les adresses à utiliser :

```
Depuis le téléphone (même Wi-Fi): https://192.168.1.20:8443/lab/
Code d'accès: 123456  (note-le, il ne sera plus affiché ; `cc2 code-acces` pour le changer)
```

### Pourquoi un certificat à installer

Le HTTPS est nécessaire pour installer l'appli, garder l'écran allumé et recevoir les notifications. Comme l'atelier
n'a pas de nom de domaine public, il crée sa **propre autorité de certification** (dans `.certs/`, clé privée lisible
par toi seul) et signe avec elle le certificat du serveur. Chaque appareil doit faire confiance à cette autorité une
fois. Le certificat du serveur se renouvelle tout seul, même si l'adresse de la machine change.

### Le guide pas à pas

Sur la machine de l'atelier, le bouton **Téléphone** (en haut) montre les étapes pour Android, iPhone et ChromeOS :

1. **Certificat (une seule fois).** Un QR code télécharge `atelier-cc2.crt`.
   - **Android** : Paramètres → Sécurité → Chiffrement et identifiants → Installer un certificat → Certificat CA.
   - **iPhone** : ouvre le fichier téléchargé (Réglages → Profil téléchargé → Installer), puis **Réglages → Général →
     Informations → Réglages des certificats** et active la confiance totale pour « Atelier CC2 – autorité locale ».
   - Les menus changent selon les marques : cherche « certificat » dans les réglages.
2. **Ouvrir et installer.** Un second QR code ouvre l'atelier. Saisis le code d'accès, puis **Installer l'appli**
   (Android, Chrome) ou **Partager → Sur l'écran d'accueil** (iPhone, Safari).

Depuis le réseau, l'ancienne adresse en HTTP (`:8787`) ne sert plus qu'à donner le certificat et renvoie vers le HTTPS.
`--sans-https` garde un atelier en HTTP simple, sans installation en appli.

### Le code d'accès

- 6 chiffres, affichés **une seule fois** au premier lancement ; seule une empreinte chiffrée est gardée.
- Chaque appareil le demande une fois puis reste connecté 30 jours. Après 5 erreurs, 5 minutes d'attente.
- La machine de l'atelier elle-même n'en a jamais besoin.
- `uv run cc2 code-acces` le change et déconnecte tous les appareils.

## La tablette murale

Une vieille tablette devient l'écran de l'imprimante : bouton **Tableau** dans l'atelier, ou
`https://<adresse de l'atelier>:8443/lab/tableau.html`. Même certificat et même code que le téléphone ; elle s'installe
aussi en appli.

- La **caméra** en grand, avec le nom de l'impression, la progression et l'état de l'IA.
- L'**impression** : pourcentage, temps restant, heure de fin, couche, couleur en cours et prochaines couleurs.
- La **coupe** : la pièce vue de face, les couches imprimées en couleur, et la couche en cours vue du dessus.
- **Températures**, **bobines** du CANVAS, **alertes** en direct avec un son.
- **Au repos** : la dernière impression (photo, durée, coût), le total du mois, l'entretien à faire.
- **Commandes** : lumière, pause et reprise, **arrêt en gardant le doigt appuyé 2 secondes** (pas d'arrêt par erreur).
- **Écran allumé** en continu, **plein écran**, **mode nuit** (écran atténué de 22 h à 7 h quand rien n'imprime, ou à
  la main ; une fin d'impression ou un problème le rallume).

Elle est écrite pour les navigateurs anciens et marche en paysage comme en portrait. Conseil : tablette sur secteur,
et dans ses réglages « ne jamais éteindre l'écran pendant la charge ».

**Tablette ChromeOS** : ouvre `http://<adresse de l'atelier>:8787/lab/ca.crt` dans Chrome, puis **Paramètres →
Confidentialité et sécurité → Sécurité → Gérer les certificats → Autorités → Importer** (ou
`chrome://certificate-manager`) et coche « Faire confiance à ce certificat pour identifier des sites Web ». Ouvre
ensuite le tableau et installe-le (**⋮ → Installer**).

## Hors de la maison, avec Tailscale

L'atelier pilote une imprimante qui chauffe à 300 °C : **n'ouvre pas de port sur ta box**. Utilise plutôt un réseau
privé entre tes appareils. [Tailscale](https://tailscale.com) est gratuit pour un usage personnel et ne demande aucun
réglage de la box.

1. Installe Tailscale sur la **machine de l'atelier** :
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo systemctl enable --now tailscaled     # sur certains serveurs, le service ne démarre pas tout seul
   sudo tailscale up                          # ouvre le lien affiché pour l'ajouter à ton compte
   ```
2. Installe l'appli Tailscale sur le **téléphone**, connectée au même compte.
3. Dans la console d'administration de Tailscale, garde **MagicDNS** activé : chaque machine a alors un nom du type
   `mon-pc.tailXXXX.ts.net`.
4. **Redémarre l'atelier.** Il voit Tailscale, ajoute ce nom à son certificat et l'affiche au lancement :
   ```
   Hors de chez toi (Tailscale): https://mon-pc.tailXXXX.ts.net:8443/lab/
   ```
5. Sur le téléphone, ouvre cette adresse (le certificat déjà installé suffit) et installe l'appli depuis elle : elle
   marchera à la maison comme ailleurs.

Les alertes ntfy contiennent alors un lien qui ouvre l'atelier par cette adresse.

## Sécurité, en résumé

- Sans `--reseau`, rien n'est visible depuis le réseau : l'atelier n'écoute que `127.0.0.1`.
- Avec `--reseau` : HTTPS, code d'accès obligatoire (sauf sur la machine elle-même), essais limités, session dans un
  cookie protégé.
- Toute action (lancer, arrêter, supprimer, régler) est refusée si elle vient d'un autre site que l'atelier.
- La caméra de l'imprimante (port 8080) reste ouverte à tout le réseau local : c'est l'imprimante qui le veut.
