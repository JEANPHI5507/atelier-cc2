"""Intégration du firmware check dans le code existant.

Ce module montre comment intégrer le gestionnaire de firmware
dans les différents composants de l'application.
"""

from __future__ import annotations

import logging

from .firmware import firmware_manager

logger = logging.getLogger(__name__)


def check_firmware_on_connection(attrs) -> dict:
    """Vérifie le firmware lors de la connexion à l'imprimante.
    
    Cette fonction doit être appelée après avoir récupéré les attributs
    de l'imprimante (via pycentauri).
    
    Args:
        attrs: Objet Attributes de pycentauri contenant firmware_version
        
    Returns:
        dict: Informations sur le firmware et le mode safe
    """
    version_string = getattr(attrs, "firmware_version", None)

    if version_string:
        firmware_manager.set_detected_version(version_string)

        info = firmware_manager.get_safe_mode_info()

        if firmware_manager.safe_mode:
            logger.warning(
                f"Firmware inconnu détecté: {version_string}. "
                f"Mode safe activé. Certaines commandes seront bloquées."
            )

        return info
    logger.warning("Impossible de récupérer la version du firmware")
    return firmware_manager.get_safe_mode_info()


def can_execute_printer_command(command: str, printer=None) -> tuple[bool, str]:
    """Vérifie si une commande peut être exécutée sur l'imprimante.
    
    Args:
        command: Nom de la commande à vérifier
        printer: Objet printer de pycentauri (optionnel)
        
    Returns:
        tuple: (is_allowed, message)
    """
    if firmware_manager.is_command_safe(command):
        return True, ""

    # Récupérer le message de blocage
    blocked_info = firmware_manager.get_blocked_commands()
    reason = blocked_info.get(command, "Commande non autorisée en mode safe")

    warning = firmware_manager.get_warning_message()

    return False, f"{reason}. {warning}"


def get_firmware_status_for_ui() -> dict:
    """Retourne les informations sur le firmware pour l'interface utilisateur.
    
    Returns:
        dict: Informations à afficher dans l'UI
    """
    info = firmware_manager.get_safe_mode_info()

    # Ajouter un message utilisateur
    if info["safe_mode"]:
        info["user_message"] = (
            "⚠️ Votre imprimante a un firmware non testé. "
            "L'atelier fonctionne en mode sécurisé. "
            "Certaines commandes doivent être exécutées sur l'écran de l'imprimante."
        )
    else:
        info["user_message"] = "✅ Firmware supporté - Toutes les fonctionnalités sont disponibles"

    return info


def get_blocked_commands_list() -> list[dict]:
    """Retourne la liste des commandes bloquées pour l'UI.
    
    Returns:
        list: Liste des commandes bloquées avec leurs raisons
    """
    blocked = firmware_manager.get_blocked_commands()

    return [
        {
            "command": cmd,
            "reason": reason,
            "action": "Doit être faite sur l'écran de l'imprimante"
        }
        for cmd, reason in blocked.items()
    ]


# Exemple d'utilisation dans connexion.py
# ==========================================
#
# Dans la fonction check() de connexion.py, après avoir récupéré attrs :
#
#     from . import firmware_integration
#     firmware_info = firmware_integration.check_firmware_on_connection(attrs)
#     out["firmware_info"] = firmware_info
#
# ==========================================


# Exemple d'utilisation dans app.py
# ==========================================
#
# Avant d'exécuter une commande dangereuse :
#
#     from . import firmware_integration
#     can_execute, message = firmware_integration.can_execute_printer_command("homing")
#     if not can_execute:
#         raise HTTPException(403, message)
#
# ==========================================


# Exemple d'utilisation dans l'API
# ==========================================
#
#     @router.get("/api/firmware/status")
#     async def get_firmware_status():
#         from . import firmware_integration
#         return firmware_integration.get_firmware_status_for_ui()
#
#     @router.get("/api/firmware/blocked-commands")
#     async def get_blocked_commands():
#         from . import firmware_integration
#         return firmware_integration.get_blocked_commands_list()
#
# ==========================================
