import base64
import json
import logging
import os
import requests
from typing import Optional

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


class MinecraftSkinDownloader:
    """
    Einfache Klasse zum Herunterladen von Minecraft-Skins.
    
    Beispiele:
        downloader = MinecraftSkinDownloader()
        
        # Skin nach UUID herunterladen
        downloader.download_by_uuid("069a79f4-44e9-4726-a5be-fca90e38aaf5", "skin.png")
        
        # Skin nach Spielername herunterladen
        downloader.download_by_name("Steve", "skin.png")
    """
    
    MOJANG_SESSION_SERVER = "https://sessionserver.mojang.com/session/minecraft/profile"
    MOJANG_API = "https://api.mojang.com/users/profiles/minecraft"
    
    def download_by_uuid(self, uuid: str, output_path: str) -> bool:
        """
        Lädt einen Minecraft-Skin basierend auf der UUID herunter.
        
        Args:
            uuid: Die UUID des Spielers (mit oder ohne Bindestriche)
            output_path: Der Pfad, wo die Skin-Datei gespeichert werden soll
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        try:
            # UUID normalisieren (Bindestriche entfernen)
            uuid_clean = uuid.replace("-", "").lower()
            
            # Spielerprofil von Mojang abrufen
            skin_url = self._get_skin_url(uuid_clean)
            if not skin_url:
                logger.warning(f"Kein Skin gefunden für UUID: {uuid}")
                return False
            
            # Skin herunterladen
            return self._download_file(skin_url, output_path)
            
        except Exception as e:
            logger.error(f"Fehler beim Download für UUID {uuid}: {e}")
            return False
    
    def download_by_name(self, player_name: str, output_path: str) -> bool:
        """
        Lädt einen Minecraft-Skin basierend auf dem Spielernamen herunter.
        
        Args:
            player_name: Der Spielername
            output_path: Der Pfad, wo die Skin-Datei gespeichert werden soll
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        try:
            # UUID aus Spielernamen abrufen
            uuid = self._get_uuid_from_name(player_name)
            if not uuid:
                logger.warning(f"Spieler nicht gefunden: {player_name}")
                return False
            
            # Skin mit UUID herunterladen
            return self.download_by_uuid(uuid, output_path)
            
        except Exception as e:
            logger.error(f"Fehler beim Download für Spieler {player_name}: {e}")
            return False
    
    def _get_uuid_from_name(self, player_name: str) -> Optional[str]:
        """Konvertiert Spielernamen zu UUID."""
        try:
            response = requests.get(
                f"{self.MOJANG_API}/{player_name}",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()["id"]
            return None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der UUID für {player_name}: {e}")
            return None
    
    def _get_skin_url(self, uuid: str) -> Optional[str]:
        """Ruft die Skin-URL vom Mojang Session Server ab."""
        try:
            response = requests.get(
                f"{self.MOJANG_SESSION_SERVER}/{uuid}",
                timeout=10
            )
            
            if response.status_code != 200:
                return None
            
            # Textur-Daten aus der Response extrahieren
            profile_data = response.json()
            properties = profile_data.get("properties", [])
            
            for prop in properties:
                if prop.get("name") == "textures":
                    # Base64-decodieren
                    texture_value = prop.get("value")
                    decoded = base64.b64decode(texture_value).decode("utf-8")
                    texture_data = json.loads(decoded)
                    
                    # Skin-URL extrahieren
                    skin_url = texture_data.get("textures", {}).get("SKIN", {}).get("url")
                    return skin_url
            
            return None
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Skin-URL für UUID {uuid}: {e}")
            return None
    
    def _download_file(self, url: str, output_path: str) -> bool:
        """Lädt die Skin-Datei herunter und speichert sie lokal."""
        try:
            # Zielverzeichnis erstellen, falls nicht vorhanden
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            
            # Datei herunterladen
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            
            # Datei speichern
            with open(output_path, "wb") as f:
                f.write(response.content)
            
            logger.info(f"Skin erfolgreich heruntergeladen: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Herunterladen der Datei {url}: {e}")
            return False


# Beispielverwendung
if __name__ == "__main__":
    downloader = MinecraftSkinDownloader()
    
    # Beispiel 1: Nach UUID herunterladen
    uuid = "069a79f4-44e9-4726-a5be-fca90e38aaf5"  # Steve
    downloader.download_by_uuid(uuid, "steve_skin.png")
    
    # Beispiel 2: Nach Spielernamen herunterladen
    # downloader.download_by_name("Steve", "steve_skin.png")
