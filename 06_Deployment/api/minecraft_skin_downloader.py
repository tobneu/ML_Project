import base64, json, os, requests
from typing import Optional


class MinecraftSkinDownloader:
    # API Ref: https://minecraft.wiki/w/Mojang_API#Query_player's_skin_and_cape
    MOJANG_SESSION_SERVER = "https://sessionserver.mojang.com/session/minecraft/profile" # for skins
    MOJANG_API = "https://api.mojang.com/users/profiles/minecraft"

    def download_by_uuid(self, uuid: str, output_path: str) -> bool:
        # Download skin by UUID
        try:
            skin_url = self._get_skin_url(uuid.replace("-", "").lower())
            return self._download_file(skin_url, output_path) if skin_url else False
        except Exception as e:
            print(f"Error for UUID {uuid}: {e}")
            return False

    def download_by_name(self, player_name: str, output_path: str) -> bool:
        # Download skin by player name
        try:
            uuid = self._get_uuid_from_name(player_name)
            return self.download_by_uuid(uuid, output_path) if uuid else False
        except Exception as e:
            print(f"Error for player {player_name}: {e}")
            return False

    # API Ref: https://minecraft.wiki/w/Mojang_API#Query_player's_UUID
    def _get_uuid_from_name(self, player_name: str) -> Optional[str]:
        try:
            res = requests.get(f"{self.MOJANG_API}/{player_name}", timeout=10)
            return res.json()["id"] if res.status_code == 200 else None
        except Exception:
            return None

    def _get_skin_url(self, uuid: str) -> Optional[str]:
        try:
            res = requests.get(f"{self.MOJANG_SESSION_SERVER}/{uuid}", timeout=10)
            if res.status_code != 200: return None

            for p in res.json().get("properties", []):
                if p.get("name") == "textures":
                    data = json.loads(base64.b64decode(p.get("value")).decode("utf-8"))
                    return data.get("textures", {}).get("SKIN", {}).get("url")
            return None
        except Exception:
            return None

    def _download_file(self, url: str, output_path: str) -> bool:
        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            res = requests.get(url, timeout=20)
            res.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(res.content)
            print(f"Downloaded: {output_path}")
            return True
        except Exception:
            return False


if __name__ == "__main__":
    MinecraftSkinDownloader().download_by_uuid("dda6ea83-75bc-4f9f-b2bd-eb5f2e6c297a", "spiderman.png")