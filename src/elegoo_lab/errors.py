"""CC2 error codes in plain French: what happened and what to do.

The code list and its meanings come from Elegoo's own firmware source (github.com/elegooofficial/
CentauriCarbon2, ``elegoo/common/exception_handler.h``, namespace ErrorCode). The advice after each
meaning is the workshop's: generic and safe, plus owner reports where they exist (printer-hub.com,
OpenCentauri changelogs), marked "signalé". Codes not in the list fall back to "look at the screen".
"""

from __future__ import annotations

# code: (what the firmware says, what to do)
CODES: dict[int, tuple[str, str]] = {
    # heaters and temperature sensors
    101: ("Le plateau chauffant ne monte pas en température comme prévu",
          "Éteins puis rallume. Si ça revient, vérifie le branchement du plateau et contacte le support Elegoo."),
    102: ("Capteur de température du plateau défaillant", "Éteins puis rallume ; si ça revient, contacte le support Elegoo."),
    103: ("La buse ne chauffe pas comme prévu",
          "Éteins puis rallume ; vérifie que la tête est bien branchée. Sinon, contacte le support Elegoo."),
    104: ("Capteur de température de la buse défaillant", "Éteins puis rallume ; si ça revient, contacte le support Elegoo."),
    108: ("Le plateau est en surchauffe", "Éteins l'imprimante, laisse refroidir, et contacte le support Elegoo si ça se reproduit."),
    902: ("Le caisson est en surchauffe", "Ouvre le capot et laisse refroidir, puis relance."),
    # motion, sensors, fans
    304: ("Échec de la mise en origine de l'axe Z",
          "Vérifie que rien ne bloque l'axe Z ni le plateau, puis relance. Signalé : tiges X/Y sales ou sèches faussent la mise en origine."),
    401: ("Accéléromètre de la tête défaillant", "Éteins puis rallume ; si ça revient, contacte le support Elegoo."),
    701: ("Ventilateur de la carte mère en défaut", "Vérifie qu'il tourne librement ; sinon contacte le support Elegoo."),
    702: ("Ventilateur de la gorge de la buse en défaut", "Éteins et vérifie qu'il tourne librement : sans lui, la gorge de la buse peut surchauffer."),
    703: ("Ventilateur de la pièce en défaut", "Vérifie qu'il tourne librement et que rien ne l'obstrue."),
    704: ("Échec du nivellement du plateau",
          "Pose l'imprimante sur un support rigide et plat, plateau propre et bien en place, puis relance. "
          "Signalé : si la buse insiste toujours au même endroit, arrête (elle peut abîmer le PEI) et rebranche les câbles des capteurs de pesée."),
    705: ("Le ventilateur n° 1 est en défaut", "Vérifie qu'il tourne librement ; sinon contacte le support Elegoo."),
    706: ("Ventilateur du caisson en défaut", "Vérifie qu'il tourne librement ; sinon contacte le support Elegoo."),
    707: ("Le capot avant de la tête (avec son ventilateur) s'est décroché",
          "Remets-le en place et vérifie ses 3 aimants. Signalé : des déchets de purge qui s'accumulent sous la tête peuvent le déloger : "
          "vide le bac de purge et nettoie la goulotte et l'essuyeur."),
    801: ("La communication avec la tête d'impression est perdue",
          "Éteins et débranche avant de toucher à quoi que ce soit, puis vérifie le câble USB-C de la tête (il porte du 24 V) et ses broches."),
    802: ("La communication avec le capteur du plateau est perdue", "Éteins puis rallume ; vérifie les câbles sous le plateau."),
    803: ("Erreur système",
          "Éteins puis rallume. Signalé : parfois déclenchée par une commande de chauffe, corrigée en partie par le firmware 02.00.02.00."),
    # exhaust grille
    1101: ("L'ouverture de la grille d'extraction a échoué", "Vérifie que rien ne bloque la grille d'extraction, puis relance."),
    1103: ("La fermeture de la grille d'extraction a échoué", "Vérifie que rien ne bloque la grille d'extraction, puis relance."),
    # CANVAS
    1210: ("La communication avec le CANVAS est coupée",
           "Vérifie le câble de liaison du CANVAS (signalé : LED rouges et blocages viennent d'un mauvais contact), puis rallume."),
    1211: ("Plus de filament (bobine vide)", "Charge une nouvelle bobine dans le canal indiqué puis reprends l'impression."),
    1220: ("Un filament anormal est détecté dans l'extrudeur", "Retire le filament à la main, puis recharge."),
    1231: ("Le coupe-filament n'a pas été enfoncé pendant la coupe",
           "Vérifie que la butée près de la porte avant est bien serrée et que le levier du coupeur revient seul."),
    1232: ("Le coupe-filament ne s'est pas relâché normalement", "Vérifie que le levier du coupeur revient seul et que rien ne le bloque."),
    1241: ("Filament non détecté pendant l'auto-test de chargement",
           "Le tube PTFE du canal est peut-être débranché : vérifie qu'il est enfoncé aux deux bouts."),
    1242: ("Chargement trop long : le filament patine ou l'extrudeur est bouché",
           "Retire les morceaux de filament (le multiplexeur s'ouvre en pinçant ses clips), sèche la bobine si elle est cassante, puis recharge en tenant le filament jusqu'à ce qu'il s'engage."),
    1243: ("Chargement anormal : l'extrudeur est probablement bouché",
           "Vérifie que la buse n'est pas bouchée. Signalé : l'option « ramming » du slicer peut la provoquer (l'atelier la désactive)."),
    1251: ("Retrait anormal : un filament est peut-être cassé dans l'extrudeur",
           "Retire les morceaux entre le CANVAS et la tête, vérifie le diamètre du filament (1,75 mm), puis recharge."),
    1252: ("Retrait trop long : le filament patine dans le canal", "Retire les morceaux dans le répartiteur et recharge la bobine."),
    1260: ("Filament cassé ou fin de bobine (rupture)", "Retire le morceau, recharge un filament et reprends."),
    1262: ("Le coupe-filament fonctionne mal", "Vérifie la butée près de la porte avant et le retour du levier."),
    1263: ("Filament emmêlé", "Démêle la bobine, vérifie qu'elle tourne librement, puis recharge. Un filament vieux ou humide casse plus souvent."),
    1264: ("Bouchon du filament externe anormal", "Vérifie le bouchon et le tube du filament externe."),
}


def explain(codes: list[int] | None) -> list[dict[str, object]]:
    out = []
    for c in codes or []:
        try:
            c = int(c)
        except (TypeError, ValueError):
            continue
        what, fix = CODES.get(c, (f"Erreur {c}", "Regarde l'écran de l'imprimante : il donne le détail et la marche à suivre."))
        out.append({"code": c, "titre": what, "conseil": fix})
    return out


def sentence(codes: list[int] | None) -> str:
    """One line for an alert: the first code explained, the others listed."""
    ex = explain(codes)
    if not ex:
        return ""
    first = ex[0]
    more = f" (autres codes : {', '.join(str(e['code']) for e in ex[1:])})" if len(ex) > 1 else ""
    return f"{first['titre']} (code {first['code']}) : {first['conseil']}{more}"
