import re
import base64
import random
import socket
import urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests

# ================== НАСТРОЙКИ ==================
OUTPUT_FILE = "sub.txt"

# Дата окончания подписки (показывается в клиенте). Поменяй когда нужно.
EXPIRE_DATE = "2026-11-09"

# True = отдавать подписку в base64, False = обычным текстом
USE_BASE64 = False

# Служебные строки в начале файла (читает Happ и совместимые клиенты)
HEADER_LINES = [
    "#profile-title: WrongSideVPN",
    "#profile-update-interval: 1",
    "#announce: ⚠️ Обходы белых списков работают только на мобильном интернете",
]

# Фейковые "ключи" с текстом сверху списка серверов
CUSTOM_HEADERS = [
    "👅t.me/WrongSideVPN👅"
]

SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-SNI-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-all.txt",
    "https://github.com/zieng2/wl/blob/main/vless_lite.txt",
    "https://github.com/zieng2/wl/blob/main/vless_universal.txt",
]

MAX_CIDR = 5      # сколько CIDR-серверов брать
MAX_WIFI = 5      # сколько обычных (wifi) серверов брать
# ===============================================


def to_raw(url: str) -> str:
    """github.com/.../blob/... -> raw.githubusercontent.com/..."""
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url


def generate_dummy(name: str) -> str:
    encoded_name = urllib.parse.quote(name)
    return f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:80?type=tcp&security=none#{encoded_name}"


def check_server_alive(key: str) -> bool:
    """Проверяет доступность сервера по TCP порту."""
    try:
        parts = key.split("@")
        if len(parts) < 2:
            return False
        host_port = parts[1].split("?")[0].split("#")[0]

        if "]:" in host_port:
            host, port_str = host_port.split("]:")
            host = host.lstrip("[")
        else:
            host, port_str = host_port.split(":")

        with socket.create_connection((host, int(port_str)), timeout=2.5):
            return True
    except Exception:
        return False


def pick_alive(candidates: list, limit: int) -> list:
    alive = []
    if limit <= 0:
        return alive
    with ThreadPoolExecutor(max_workers=20) as executor:
        for key, ok in executor.map(lambda k: (k, check_server_alive(k)), candidates):
            if ok:
                alive.append(key)
                if len(alive) >= limit:
                    break
    return alive


def get_fresh_vless_keys() -> list:
    cidr_candidates = []
    normal_candidates = []
    headers_req = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    bad_words = ["🛸", "🪐", "t.me", "wrongside", "update", "github", "127.0.0.1", "0.0.0.0"]

    for url in SOURCES:
        try:
            res = requests.get(to_raw(url), headers=headers_req, timeout=10)
            if res.status_code != 200:
                print(f"{url}: HTTP {res.status_code}")
                continue

            found = re.findall(r"(vless://[^\s\r\n]+)", res.text)
            is_cidr_source = "cidr" in url.lower()

            for key in found:
                clean_key = key.strip()
                name = ""
                if "#" in clean_key:
                    name = urllib.parse.unquote(clean_key.split("#", 1)[1]).lower()

                if any(w in name or w in clean_key.lower() for w in bad_words):
                    continue

                target = cidr_candidates if (is_cidr_source or "cidr" in name) else normal_candidates
                if clean_key not in target:
                    target.append(clean_key)

        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")

    print(f"Кандидатов CIDR: {len(cidr_candidates)}, Обычных: {len(normal_candidates)}")

    random.shuffle(cidr_candidates)
    random.shuffle(normal_candidates)

    print("Проверяем CIDR серверы...")
    cidr_alive = pick_alive(cidr_candidates[:80], MAX_CIDR)

    print("Проверяем обычные (wifi) серверы...")
    wifi_alive = pick_alive(normal_candidates[:100], MAX_WIFI)

    print(f"Живых CIDR: {len(cidr_alive)}/{MAX_CIDR}, wifi: {len(wifi_alive)}/{MAX_WIFI}")
    return wifi_alive + cidr_alive


def build_userinfo() -> str:
    expire_ts = int(datetime.strptime(EXPIRE_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    return f"#subscription-userinfo: upload=0; download=0; total=0; expire={expire_ts}"


def write_subscription(alive_keys: list):
    if not alive_keys:
        raise Exception("Не удалось найти ни одного живого сервера. Файл не изменён.")

    lines = list(HEADER_LINES)
    lines.append(build_userinfo())
    lines.extend(generate_dummy(t) for t in CUSTOM_HEADERS)
    lines.extend(alive_keys)

    content = "\n".join(lines) + "\n"
    if USE_BASE64:
        content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Готово: {OUTPUT_FILE}, серверов: {len(alive_keys)}")


if __name__ == "__main__":
    write_subscription(get_fresh_vless_keys())
    
