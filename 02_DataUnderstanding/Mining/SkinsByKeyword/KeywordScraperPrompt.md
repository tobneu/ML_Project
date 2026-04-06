Rolle: Du bist ein Senior Python Developer und Experte für Web Scraping.

Kontext: Ich benötige ein Python-Skript, um Bilddaten (Minecraft-Skins, 64x64 Pixel PNGs) für das Training eines Machine-Learning-Modells zu sammeln. Die Datenquelle ist minecraftskins.com.

Die Herausforderung: Die Seite ist streng durch Cloudflare geschützt. Standard-Requests (requests.get) resultieren sofort in einem HTTP 403 Forbidden Fehler.

Ziel-Architektur & Workflow:
Schreibe ein sauberes, modulares Python-Skript, das folgende Schritte ausführt:

Cloudflare Umgehung: Verwende zwingend die Bibliothek cloudscraper (cloudscraper.create_scraper(...)), um die Suchseiten aufzurufen. Verwende keine hartcodierten Cookies oder User-Agent-Header, lass cloudscraper das Fingerprinting selbst aushandeln.

Suchseite parsen (Schritt 1):

Das Skript iteriert über Suchseiten mit folgendem URL-Muster: https://www.minecraftskins.com/search/mostvotedskin/[KEYWORD]/[PAGE]/

Nutze BeautifulSoup, um die Suchseite zu parsen. Finde alle Links zu den Skins (diese sehen meist so aus: /skin/19755510/crimson/).

Extrahiere die Skin-ID (im Beispiel: 19755510) aus der URL.

Bild-Download (Schritt 2 - WICHTIGER SHORTCUT):

Gehe nicht auf die Detailseite des Skins.

Nutze stattdessen den direkten Download-Endpunkt: Rufe die URL https://www.minecraftskins.com/skin/download/[SKIN_ID] auf.

Speichere die zurückgegebene Datei (es ist ein PNG) lokal im Verzeichnis data/skins/seed/[KEYWORD]/[KEYWORD]_[SKIN_ID].png ab.

Politeness & Rate-Limiting:

Baue nach jedem Download ein zufälliges time.sleep() (z.B. 1 bis 3 Sekunden) ein.

Implementiere eine Retry-Logik (z.B. max 3 Versuche), falls Cloudflare temporär einen 403 oder 429 wirft.

Abbruchbedingung:

Die Funktion soll ein target_count (z.B. 50 oder 100) als Parameter akzeptieren und stoppen, sobald ausreichend Skins für das Keyword erfolgreich heruntergeladen wurden.

Anforderungen an den Code:

Verwende Type Hints und ordentliches Logging (via logging Modul, keine einfachen print statements).

Teile den Code in saubere Funktionen oder eine Klasse (z.B. SkindexScraper) auf.

Erstelle einen if __name__ == '__main__': Block, der das Skript beispielhaft für das Keyword "uniform" mit einem Target von 25 Skins startet.