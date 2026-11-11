# Première connexion à la CC2

[← Retour au README](../README.md)

L'atelier parle à l'imprimante sur le réseau local, comme le logiciel d'Elegoo, mais sans passer par le cloud.
Il lui faut trois choses : l'imprimante en **mode réseau local**, son **adresse IP** et son **code d'accès**.

## 1. Préparer l'imprimante

1. Sur l'écran de la CC2 : **Paramètres → Réseau**. Connecte-la au Wi-Fi (ou au câble) de la maison si ce n'est pas
   fait, puis active **« LAN Only »** (réseau local seulement).
   Ce mode coupe les services en ligne d'Elegoo (application, IA et vidéo dans le cloud) : l'atelier les remplace.
2. Sur le même écran, note **l'adresse IP** (du type `192.168.1.42`) et le **code d'accès** (6 caractères).
3. Conseillé : dans les réglages de ta box internet, donne une **adresse fixe** à l'imprimante (bail DHCP statique).
   Sinon l'adresse peut changer après une coupure de courant, et l'atelier ne la trouvera plus.

## 2. L'onglet Démarrage

Lance l'atelier (`uv run cc2 --control dash`) et ouvre l'onglet **Démarrage**. Il guide en quatre étapes.

1. **Connecter l'imprimante.** Saisis l'IP et le code d'accès, puis **Tester la connexion**. Le test vérifie dans
   l'ordre que l'imprimante répond sur le réseau, que le code est le bon et que le mode LAN est actif ; à chaque échec,
   il dit quoi corriger. **Enregistrer** écrit `config.toml`. Relance ensuite l'atelier pour qu'il se connecte
   (ou `systemctl --user restart cc2-atelier` s'il tourne en service).
2. **Charger le CANVAS.** Quatre bobines de PLA de couleurs bien différentes pour les tests. L'atelier lit le CANVAS
   (couleur et matière de chaque bobine) : vérifie dans l'onglet Imprimante que les quatre apparaissent avec la bonne
   matière.
3. **Imprimer les pièces de test**, générées et tranchées à la demande, chacune avec ce qu'il faut regarder :
   première couche (5 carrés, 3 min), cube de 20 mm (14 min), test CANVAS en 4 couleurs (42 min), ajustement des
   chevilles (43 min).
4. **Régler l'assemblage.** D'après le test des chevilles, choisis le jeu qui s'emboîte bien. Il sert ensuite à toutes
   les pièces découpées (0,15 mm par défaut).

## 3. En ligne de commande

```bash
uv run cc2 doctor          # vérifie config.toml, l'imprimante (MQTT, port 1883) et ComfyUI
uv run cc2 status          # l'état de l'imprimante, une fois (lecture seule)
uv run cc2 canvas          # les bobines du CANVAS
```

Les commandes qui **modifient** quelque chose (lancer, arrêter, chauffer, lumière) demandent `--control` :
`uv run cc2 --control light on`.

## Si ça ne se connecte pas

- **« injoignable »** : l'imprimante est-elle allumée, sur le même réseau que la machine de l'atelier ? Essaie
  `ping <IP>`. Un réseau invité ou un Wi-Fi « isolé » de la box empêche les appareils de se voir.
- **« code refusé »** : le code change si l'imprimante est réinitialisée ; relis-le sur l'écran.
- **« mode LAN désactivé »** : sans « LAN Only », la CC2 n'accepte pas de connexion locale.
- **L'IP a changé** : refais l'étape 1 dans l'onglet Démarrage, puis fixe l'adresse dans la box.

Plus de cas : [Dépannage](depannage.md).
