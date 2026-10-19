import requests
import os
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
if not WEBHOOK_URL:
    raise RuntimeError("Brak zmiennej środowiskowej DISCORD_WEBHOOK_URL!")

IMGW_URL = "https://danepubliczne.imgw.pl/api/data/warningsmeteo"
TERYT_CODE = os.environ.get("TERYT_CODE", "2005")
SENT_IDS_FILE = os.environ.get("SENT_IDS_FILE", "/data/sent_ids.txt")
INTERVAL_SECONDS = 30 * 60  # 30 minut

COLORS = {1: 0xFFFF00, 2: 0xFF8C00, 3: 0xFF0000}
ICONS = {1: "🟡", 2: "🟠", 3: "🔴"}


def load_sent_ids():
    try:
        with open(SENT_IDS_FILE, 'r') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()


def save_sent_id(warning_id):
    os.makedirs(os.path.dirname(SENT_IDS_FILE), exist_ok=True)
    with open(SENT_IDS_FILE, 'a') as f:
        f.write(f"{warning_id}\n")


def field_value(value, limit=1024):
    """Discord odrzuca puste wartości pól i dłuższe niż 1024 znaki."""
    text = str(value).strip() if value is not None else ""
    if not text:
        text = "brak"
    return text[:limit]


def fetch_warnings():
    """Zwraca listę ostrzeżeń (może być pusta) albo None przy błędzie."""
    try:
        response = requests.get(IMGW_URL, timeout=15)
    except requests.RequestException as e:
        logger.error(f"Błąd połączenia z IMGW: {e}")
        return None

    if response.status_code != 200:
        logger.error(f"Błąd pobierania danych: {response.status_code}")
        return None

    try:
        data = response.json()
    except ValueError:
        logger.error("IMGW zwrócił niepoprawny JSON")
        return None

    # Gdy nie ma ostrzeżeń, API zwraca dict {"message": "..."} zamiast listy
    if not isinstance(data, list):
        logger.info(f"Brak aktywnych ostrzeżeń (odpowiedź IMGW: {data})")
        return []

    return data


def check_warnings():
    logger.info("Sprawdzam ostrzeżenia IMGW...")
    sent_ids = load_sent_ids()

    ostrzezenia = fetch_warnings()
    if ostrzezenia is None:
        return

    filtered_warnings = []
    for ostrzezenie in ostrzezenia:
        if not isinstance(ostrzezenie, dict):
            continue

        teryt_list = [str(code) for code in ostrzezenie.get('teryt', [])]
        if TERYT_CODE in teryt_list:
            filtered_warnings.append({
                'ID': str(ostrzezenie.get('id', 'brak')),
                'Zdarzenie': ostrzezenie.get('nazwa_zdarzenia', 'brak'),
                'Stopien zagrozenia': ostrzezenie.get('stopien', 'brak'),
                'Prawdopodobienstwo': ostrzezenie.get('prawdopodobienstwo', 'brak'),
                'Obowiazuje od': ostrzezenie.get('obowiazuje_od', 'brak'),
                'Obowiazuje do': ostrzezenie.get('obowiazuje_do', 'brak'),
                'Opublikowano': ostrzezenie.get('opublikowano', 'brak'),
                'Opis': ostrzezenie.get('tresc', 'brak'),
                'Komentarz': ostrzezenie.get('komentarz', 'brak')
            })

    new_count = 0
    for ostrzezenie in filtered_warnings:
        if ostrzezenie['ID'] in sent_ids:
            continue

        stopien = ostrzezenie['Stopien zagrozenia']
        stopien_int = int(stopien) if str(stopien).isdigit() else 0
        color = COLORS.get(stopien_int, 0x808080)
        icon = ICONS.get(stopien_int, "⚪")

        komentarz = ostrzezenie['Komentarz']
        if str(komentarz).strip().lower() in ('brak', 'brak.', '', 'none'):
            komentarz = None

        fields = [
            {"name": "🌡️ Zdarzenie", "value": field_value(ostrzezenie['Zdarzenie']), "inline": True},
            {"name": "📊 Stopień zagrożenia", "value": field_value(f"{icon} {stopien}"), "inline": True},
            {"name": "🎯 Prawdopodobieństwo", "value": field_value(f"{ostrzezenie['Prawdopodobienstwo']}%"), "inline": True},
            {"name": "🕐 Obowiązuje od", "value": field_value(ostrzezenie['Obowiazuje od']), "inline": True},
            {"name": "🕑 Obowiązuje do", "value": field_value(ostrzezenie['Obowiazuje do']), "inline": True},
            {"name": "📅 Opublikowano", "value": field_value(ostrzezenie['Opublikowano']), "inline": True},
            {"name": "📝 Opis", "value": field_value(ostrzezenie['Opis']), "inline": False},
        ]
        if komentarz:
            fields.append({"name": "💬 Komentarz", "value": field_value(komentarz), "inline": False})

        embed = {
            "title": "⚠️ Nowe ostrzeżenie meteorologiczne",
            "color": color,
            "fields": fields,
        }

        try:
            discord_response = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=10)
            if discord_response.status_code in (200, 204):
                save_sent_id(ostrzezenie['ID'])
                new_count += 1
                logger.info(f"Wysłano ostrzeżenie ID: {ostrzezenie['ID']}")
            else:
                logger.error(
                    f"Błąd wysyłania do Discorda: {discord_response.status_code} "
                    f"{discord_response.text[:200]}"
                )
        except requests.RequestException as e:
            logger.error(f"Błąd połączenia z Discordem: {e}")

    if new_count == 0:
        logger.info("Brak nowych ostrzeżeń.")
    else:
        logger.info(f"Wysłano {new_count} nowych ostrzeżeń.")


if __name__ == "__main__":
    logger.info(f"Bot IMGW uruchomiony. Interwał: {INTERVAL_SECONDS // 60} minut.")
    while True:
        try:
            check_warnings()
        except Exception:
            # Nieoczekiwany błąd nie powinien ubijać kontenera i zapętlać restartów
            logger.exception("Nieoczekiwany błąd w check_warnings()")
        logger.info(f"Następne sprawdzenie za {INTERVAL_SECONDS // 60} minut.")
        time.sleep(INTERVAL_SECONDS)
