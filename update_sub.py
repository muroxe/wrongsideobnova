import os
import re
import json
import base64
import random
import shutil
import socket
import tempfile
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests

# ================== НАСТРОЙКИ ==================
OUTPUT_FILE = "sub.txt"

# Основная подписка бесконечная (expire=0)
SITE_URL = "https://sub.wrongside.ru"
OUT_DIR = "site"

# Пул для TikTok-подписок (его раздаёт бот). Лежит по секретному пути.
TT_TARGET = 100        # сколько рабочих серверов в пуле
TT_MAX_TEST = 800      # сколько кандидатов максимум проверять
TT_POOL_PATH = os.environ.get("TT_POOL_PATH", "")  # секретная строка для адреса пула

# True = отдавать подписку в base64, False = обычным текстом
USE_BASE64 = False

HEADER_LINES = [
    "#profile-title: WrongSideVPN",
    "#profile-update-interval: 1",
    "#announce: ⚠️ Обходы белых списков работают только на мобильном интернете",
]

CUSTOM_HEADERS = [
    "👅t.me/WrongSideVPN👅"
]

# Сколько серверов каждого типа брать (итого 10)
MAX_WIFI = 5       # обычные серверы (не CIDR)
MAX_CIDR = 3       # CIDR (белые списки РФ)
MAX_FOREIGN = 2    # иностранные серверы из общих списков

# Сколько кандидатов максимум проверять в каждой группе
MAX_TEST = 150

# Источники: РФ
SOURCES_WIFI = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-SNI-RU-all.txt",
    "https://github.com/zieng2/wl/blob/main/vless_lite.txt",
    "https://github.com/zieng2/wl/blob/main/vless_universal.txt",
]
SOURCES_CIDR = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-all.txt",
]
# Источники: иностранные серверы (можно добавлять свои)
SOURCES_FOREIGN = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt",
]

# Тест реального соединения через xray
TEST_URL = "https://www.gstatic.com/generate_204"
TEST_TIMEOUT = 8
XRAY_BIN = os.environ.get("XRAY_BIN", "xray")
# ===============================================

BAD_WORDS = ["🛸", "🪐", "t.me", "wrongside", "update", "github", "127.0.0.1", "0.0.0.0"]


# ---------- загрузка ----------
def to_raw(url: str) -> str:
    if "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url


def decode_base64_safely(data: str) -> str:
    cleaned = data.strip().replace(" ", "").replace("\n", "").replace("\r", "")
    cleaned += "=" * (-len(cleaned) % 4)
    try:
        return base64.b64decode(cleaned).decode("utf-8", errors="ignore")
    except Exception:
        return data


def load_keys(urls: list) -> list:
    headers_req = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    keys = []
    for url in urls:
        try:
            res = requests.get(to_raw(url), headers=headers_req, timeout=15)
            if res.status_code != 200:
                print(f"{url}: HTTP {res.status_code}")
                continue
            text = res.text
            if "vless://" not in text:
                text = decode_base64_safely(text)
            for key in re.findall(r"(vless://[^\s\r\n]+)", text):
                key = key.strip()
                name = ""
                if "#" in key:
                    name = urllib.parse.unquote(key.split("#", 1)[1]).lower()
                if "@" in name or any(w in name or w in key.lower() for w in BAD_WORDS):
                    continue
                if key not in keys:
                    keys.append(key)
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
    return keys


# ---------- vless:// -> конфиг xray ----------
def parse_vless(key: str):
    """Возвращает outbound для xray или None, если формат не поддерживается."""
    try:
        u = urllib.parse.urlsplit(key)
        if u.scheme != "vless" or not u.username or not u.hostname or not u.port:
            return None
        p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

        network = p.get("type", "tcp")
        security = p.get("security", "none")
        host_hdr = p.get("host", "")
        path = urllib.parse.unquote(p.get("path", "/"))

        stream = {"security": security}
        if network == "tcp":
            if p.get("headerType", "none") not in ("none", ""):
                return None
            stream["network"] = "tcp"
        elif network == "ws":
            stream["network"] = "ws"
            ws = {"path": path}
            if host_hdr:
                ws["headers"] = {"Host": host_hdr}
            stream["wsSettings"] = ws
        elif network == "grpc":
            stream["network"] = "grpc"
            stream["grpcSettings"] = {
                "serviceName": urllib.parse.unquote(p.get("serviceName", "")),
                "multiMode": p.get("mode", "") == "multi",
            }
        elif network in ("xhttp", "splithttp"):
            stream["network"] = "xhttp"
            xh = {"path": path}
            if host_hdr:
                xh["host"] = host_hdr
            if p.get("mode"):
                xh["mode"] = p["mode"]
            stream["xhttpSettings"] = xh
        elif network == "httpupgrade":
            stream["network"] = "httpupgrade"
            hu = {"path": path}
            if host_hdr:
                hu["host"] = host_hdr
            stream["httpupgradeSettings"] = hu
        else:
            return None

        if security == "tls":
            tls = {"serverName": p.get("sni") or host_hdr or u.hostname,
                   "fingerprint": p.get("fp") or "chrome"}
            if p.get("alpn"):
                tls["alpn"] = urllib.parse.unquote(p["alpn"]).split(",")
            if p.get("allowInsecure") in ("1", "true") or p.get("insecure") in ("1", "true"):
                tls["allowInsecure"] = True
            stream["tlsSettings"] = tls
        elif security == "reality":
            if not p.get("pbk"):
                return None
            stream["realitySettings"] = {
                "serverName": p.get("sni", ""),
                "fingerprint": p.get("fp") or "chrome",
                "publicKey": p["pbk"],
                "shortId": p.get("sid", ""),
                "spiderX": urllib.parse.unquote(p.get("spx", "")),
            }
        elif security != "none":
            return None

        user = {"id": urllib.parse.unquote(u.username), "encryption": p.get("encryption", "none")}
        if p.get("flow"):
            user["flow"] = p["flow"]

        return {
            "protocol": "vless",
            "settings": {"vnext": [{"address": u.hostname, "port": u.port, "users": [user]}]},
            "streamSettings": stream,
        }
    except Exception:
        return None


# ---------- проверка ----------
def check_tcp(key: str) -> bool:
    try:
        u = urllib.parse.urlsplit(key)
        with socket.create_connection((u.hostname, u.port), timeout=2.5):
            return True
    except Exception:
        return False


def check_real(key: str, port: int) -> bool:
    """Поднимает xray с этим ключом и ходит через него в интернет."""
    outbound = parse_vless(key)
    if not outbound:
        return False
    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                      "settings": {"auth": "noauth", "udp": False}}],
        "outbounds": [outbound],
    }
    tmpdir = tempfile.mkdtemp()
    cfg_path = os.path.join(tmpdir, "c.json")
    proc = None
    try:
        with open(cfg_path, "w") as f:
            json.dump(config, f)
        proc = subprocess.Popen([XRAY_BIN, "run", "-c", cfg_path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # ждём, пока xray откроет локальный порт
        started = False
        for _ in range(30):
            if proc.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    started = True
                    break
            except OSError:
                time.sleep(0.1)
        if not started:
            return False

        # два запроса подряд должны пройти
        for _ in range(2):
            r = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "-x", f"socks5h://127.0.0.1:{port}",
                 "--max-time", str(TEST_TIMEOUT), TEST_URL],
                capture_output=True, text=True)
            if r.stdout.strip() not in ("204", "200"):
                return False
        return True
    except Exception:
        return False
    finally:
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        shutil.rmtree(tmpdir, ignore_errors=True)


HAVE_XRAY = shutil.which(XRAY_BIN) is not None
if not HAVE_XRAY:
    if os.environ.get("CI"):
        raise SystemExit("xray не найден. Проверь, что в workflow есть шаг Install Xray (берите новый update_sub.yml).")
    print("ВНИМАНИЕ: xray не найден, используется только TCP-проверка (менее надёжная).")

_port_counter = [20000]


def pick_working(candidates: list, limit: int, used: set, max_test=None, chunk_size=24) -> list:
    """Проверяет кандидатов пачками, пока не наберёт limit рабочих."""
    result = []
    if limit <= 0:
        return result
    pool = [k for k in candidates if k not in used][:(max_test or MAX_TEST)]
    for i in range(0, len(pool), chunk_size):
        chunk = pool[i:i + chunk_size]
        ports = [_port_counter[0] + n for n in range(len(chunk))]
        _port_counter[0] += len(chunk)
        if HAVE_XRAY:
            fn = lambda kp: (kp[0], check_real(kp[0], kp[1]))
        else:
            fn = lambda kp: (kp[0], check_tcp(kp[0]))
        with ThreadPoolExecutor(max_workers=chunk_size) as ex:
            for key, ok in ex.map(fn, zip(chunk, ports)):
                if ok and len(result) < limit:
                    result.append(key)
                    used.add(key)
        if len(result) >= limit:
            break
    return result


# ---------- сборка ----------
def generate_dummy(name: str) -> str:
    return f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:80?type=tcp&security=none#{urllib.parse.quote(name)}"


def build_userinfo(expire_ts: int = 0) -> str:
    return f"#subscription-userinfo: upload=0; download=0; total=0; expire={expire_ts}"


def write_text(path: str, lines: list):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    content = "\n".join(lines) + "\n"
    if USE_BASE64:
        content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------- пул для TikTok ----------
def build_pool(pool_sources: list):
    if not TT_POOL_PATH:
        print("TikTok: TT_POOL_PATH не задан, пул не собираю.")
        return
    random.shuffle(pool_sources)
    print(f"TikTok: проверяю пул, цель {TT_TARGET} серверов...")
    pool = pick_working(pool_sources, TT_TARGET, set(), max_test=TT_MAX_TEST, chunk_size=48)
    print(f"TikTok: в пуле {len(pool)} рабочих серверов")
    if not pool:
        print("TikTok: пул пуст, файл не создан.")
        return
    path = os.path.join(OUT_DIR, "p", f"{TT_POOL_PATH}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(pool) + "\n")


# ---------- главная ----------
def main():
    wifi = load_keys(SOURCES_WIFI)
    cidr = load_keys(SOURCES_CIDR)
    foreign = load_keys(SOURCES_FOREIGN)
    print(f"Кандидатов: wifi {len(wifi)}, cidr {len(cidr)}, foreign {len(foreign)}")
    for lst in (wifi, cidr, foreign):
        random.shuffle(lst)

    used = set()
    cidr_ok = pick_working(cidr, MAX_CIDR, used)
    wifi_ok = pick_working(wifi, MAX_WIFI, used)
    foreign_ok = pick_working(foreign, MAX_FOREIGN, used)
    keys = wifi_ok + cidr_ok + foreign_ok
    print(f"Рабочих: wifi {len(wifi_ok)}/{MAX_WIFI}, cidr {len(cidr_ok)}/{MAX_CIDR}, "
          f"foreign {len(foreign_ok)}/{MAX_FOREIGN}")
    if not keys:
        raise Exception("Не найдено ни одного рабочего сервера. Сайт не обновлён.")

    # основная бесконечная подписка
    lines = list(HEADER_LINES) + [build_userinfo(0)]
    lines += [generate_dummy(t) for t in CUSTOM_HEADERS] + keys
    write_text(os.path.join(OUT_DIR, "sub.txt"), lines)

    # служебные файлы сайта
    with open(os.path.join(OUT_DIR, "CNAME"), "w") as f:
        f.write(SITE_URL.replace("https://", "") + "\n")
    with open(os.path.join(OUT_DIR, "index.html"), "w") as f:
        f.write("<!doctype html><title>WrongSideVPN</title>")

    # пул для TikTok-подписок
    build_pool(wifi + cidr + foreign)
    print("Готово")


if __name__ == "__main__":
    main()
