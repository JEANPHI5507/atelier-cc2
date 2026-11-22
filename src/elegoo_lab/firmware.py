"""Gestion du firmware de la CC2 et mode safe.

Ce module permet de :
- Détecter la version du firmware de l'imprimante
- Vérifier si le firmware est supporté
- Activer le mode safe pour les firmwares inconnus
- Bloquer les commandes dangereuses pour les firmwares non testés
"""

from __future__ import annotations

import logging
from typing import Optional

# 4CD Versions de firmware testées et supportées
# Format: (version_min, version_max, description)
SUPPORTED_FIRMWARE_VERSIONS = [
    ("02.00.00.00", "02.00.02.00", "Premières versions - Partiellement supportées"),
    ("02.00.02.01", "02.01.01.13", "Versions stables - Complètement supportées"),
    ("02.01.01.14", "02.99.99.99", "Nouvelles versions - Support expérimental"),
]

# 534 Versions de firmware connues pour avoir des problèmes
PROBLEMATIC_FIRMWARE = {
    "02.00.00.00": ["Problèmes de connexion MQTT"],
    "02.00.01.00": ["Bug de détection de filament"],
}

# 4BB Commandes bloquées en mode safe
# Ces commandes ne sont pas exécutées si le firmware n'est pas reconnu
BLOCKED_COMMANDS_IN_SAFE_MODE = {
    "homing": "Mise à l'origine (G28) - Doit être faite sur l'écran de l'imprimante",
    "move": "Déplacements manuels (G0, G1) - Doit être faite sur l'écran de l'imprimante",
    "calibration": "Calibrage - Doit être faite sur l'écran de l'imprimante",
    "filament_load": "Chargement de filament - Doit être faite sur l'écran de l'imprimante",
    "filament_unload": "Déchargement de filament - Doit être faite sur l'écran de l'imprimante",
    "z_offset": "Réglage du Z offset - Doit être faite sur l'écran de l'imprimante",
    "pid_tune": "Réglage PID - Doit être faite sur l'écran de l'imprimante",
}

# 527 Commandes autorisées même en mode safe
# Ces commandes sont considérées comme sûres
SAFE_COMMANDS = {
    "status": "Récupération du statut",
    "temp_get": "Lecture des températures",
    "temp_set": "Réglage des températures (pour l'impression)",
    "print_start": "Démarrage de l'impression",
    "print_stop": "Arrêt de l'impression",
    "print_pause": "Pause de l'impression",
    "print_resume": "Reprise de l'impression",
    "light_on": "Allumage de la lumière",
    "light_off": "Extinction de la lumière",
    "camera_get": "Récupération de l'image caméra",
    "file_list": "Liste des fichiers",
    "file_upload": "Upload de fichiers",
    "file_delete": "Suppression de fichiers",
}

logger = logging.getLogger(__name__)


class FirmwareVersion:
    """Représente une version de firmware et ses propriétés."""

    def __init__(self, version_string: str):
        self.version_string = version_string
        self.major, self.minor, self.patch, self.build = self._parse_version(version_string)

    @staticmethod
    def _parse_version(version_string: str) -> tuple[int, int, int, int]:
        """Parse une chaîne de version au format XX.YY.ZZ.WW."""
        try:
            parts = version_string.split(".")
            if len(parts) == 4:
                return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            elif len(parts) == 3:
                return int(parts[0]), int(parts[1]), int(parts[2]), 0
            else:
                # Version inconnue, retourner 0.0.0.0
                return 0, 0, 0, 0
        except (ValueError, AttributeError):
            return 0, 0, 0, 0

    def __str__(self) -> str:
        return self.version_string

    def __repr__(self) -> str:
        return f"FirmwareVersion('{self.version_string}')"

    def is_supported(self) -> bool:
        """Vérifie si cette version de firmware est supportée."""
        for min_ver, max_ver, _ in SUPPORTED_FIRMWARE_VERSIONS:
            if self._compare(min_ver) >= 0 and self._compare(max_ver) <= 0:
                return True
        return False

    def _compare(self, other: str) -> int:
        """Compare cette version avec une autre.
        
        Retourne:
        - Un nombre négatif si self < other
        - 0 si self == other
        - Un nombre positif si self > other
        """
        other_major, other_minor, other_patch, other_build = self._parse_version(other)
        
        if self.major != other_major:
            return self.major - other_major
        if self.minor != other_minor:
            return self.minor - other_minor
        if self.patch != other_patch:
            return self.patch - other_patch
        return self.build - other_build

    def get_support_level(self) -> str:
        """Retourne le niveau de support pour cette version."""
        for min_ver, max_ver, description in SUPPORTED_FIRMWARE_VERSIONS:
            if self._compare(min_ver) >= 0 and self._compare(max_ver) <= 0:
                return description
        return "Firmware inconnu - Mode safe activé"

    def get_known_issues(self) -> list[str]:
        """Retourne les problèmes connus pour cette version."""
        return PROBLEMATIC_FIRMWARE.get(self.version_string, [])


class FirmwareManager:
    """Gère la détection du firmware et le mode safe."""

    def __init__(self):
        self._detected_version: Optional[FirmwareVersion] = None
        self._safe_mode: bool = False

    @property
    def detected_version(self) -> Optional[FirmwareVersion]:
        """Retourne la version de firmware détectée."""
        return self._detected_version

    @property
    def safe_mode(self) -> bool:
        """Retourne True si le mode safe est activé."""
        return self._safe_mode

    @property
    def is_supported(self) -> bool:
        """Retourne True si le firmware est supporté."""
        if self._detected_version is None:
            return False
        return self._detected_version.is_supported()

    def set_detected_version(self, version_string: str) -> None:
        """Définit la version de firmware détectée."""
        self._detected_version = FirmwareVersion(version_string)
        # Activer le mode safe si le firmware n'est pas supporté
        self._safe_mode = not self._detected_version.is_supported()
        
        if self._safe_mode:
            logger.warning(
                f"Firmware inconnu détecté: {version_string}. "
                f"Mode safe activé. Certaines commandes seront bloquées."
            )
        else:
            logger.info(f"Firmware supporté détecté: {version_string}")

    def is_command_safe(self, command: str) -> bool:
        """Vérifie si une commande est autorisée.
        
        Args:
            command: Nom de la commande à vérifier
            
        Returns:
            True si la commande est autorisée, False sinon
        """
        if not self._safe_mode:
            # En mode normal, toutes les commandes sont autorisées
            return True
        
        # En mode safe, vérifier si la commande est dans la liste des commandes sûres
        if command in SAFE_COMMANDS:
            return True
        
        # Vérifier si la commande est explicitement bloquée
        if command in BLOCKED_COMMANDS_IN_SAFE_MODE:
            logger.warning(
                f"Commande bloquée en mode safe: {command}. "
                f"Raison: {BLOCKED_COMMANDS_IN_SAFE_MODE[command]}"
            )
            return False
        
        # Par défaut, autoriser la commande (pour ne pas être trop restrictif)
        logger.warning(f"Commande non vérifiée en mode safe: {command}. Autorisée par défaut.")
        return True

    def get_blocked_commands(self) -> dict[str, str]:
        """Retourne la liste des commandes bloquées en mode safe."""
        return BLOCKED_COMMANDS_IN_SAFE_MODE

    def get_warning_message(self) -> str:
        """Retourne un message d'avertissement pour l'UI."""
        if not self._safe_mode or self._detected_version is None:
            return ""
        
        return (
            f"⚠️ Firmware inconnu détecté: {self._detected_version.version_string}. "
            f"Mode safe activé. Certaines commandes doivent être exécutées sur l'écran de l'imprimante. "
            f"Niveau de support: {self._detected_version.get_support_level()}"
        )

    def get_safe_mode_info(self) -> dict[str, any]:
        """Retourne les informations sur le mode safe pour l'API."""
        if self._detected_version is None:
            return {
                "safe_mode": False,
                "firmware_detected": False,
                "firmware_version": None,
                "is_supported": False,
                "support_level": "Firmware non détecté",
                "blocked_commands": {},
            }
        
        return {
            "safe_mode": self._safe_mode,
            "firmware_detected": True,
            "firmware_version": self._detected_version.version_string,
            "is_supported": self._detected_version.is_supported(),
            "support_level": self._detected_version.get_support_level(),
            "known_issues": self._detected_version.get_known_issues(),
            "blocked_commands": BLOCKED_COMMANDS_IN_SAFE_MODE,
        }


# 3F3 Instance globale du gestionnaire de firmware
firmware_manager = FirmwareManager()


# 4CD Fonctions utilitaires

def check_firmware_version(version_string: str) -> tuple[bool, str]:
    """Vérifie si une version de firmware est supportée.
    
    Args:
        version_string: Chaîne de version du firmware
        
    Returns:
        Tuple de (is_supported, message)
    """
    fw = FirmwareVersion(version_string)
    if fw.is_supported():
        return True, f"Firmware supporté: {version_string}"
    else:
        return False, f"Firmware non supporté: {version_string} - {fw.get_support_level()}"


def is_safe_mode_active() -> bool:
    """Retourne True si le mode safe est activé."""
    return firmware_manager.safe_mode


def can_execute_command(command: str) -> bool:
    """Vérifie si une commande peut être exécutée.
    
    Args:
        command: Nom de la commande
        
    Returns:
        True si la commande peut être exécutée, False sinon
    """
    return firmware_manager.is_command_safe(command)
