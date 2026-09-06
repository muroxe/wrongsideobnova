import os
import re
import base64
import random
import urllib.parse
import requests
from datetime import datetime

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID", "d80e40f8efb3fcfacd9c631e12c73e1e")

# === ВАШИ СОБСТВЕННЫЕ ПУСТЫШКИ (ОФОРМЛЕНИЕ) ===
# Можете менять текст, добавлять эмодзи. Они будут всегда сверху списка.
CUSTOM_HEADERS = [
    "👅t.me/WrongSideVPN👅",
    f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
]

SOURCES = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-SNI-RU-all.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-all.txt"
]

def decode_base64_safely(data: str) -> str:
    cleaned = data.strip().replace(" ", "").replace("\n", "").replace("\r", "")
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += "=" * (4 - missing_padding)
    try:
        return base64.b64decode(cleaned).decode("utf-8", errors="ignore")
    except Exception:
        return data

def generate_dummy(name: str) -> str:
    # Генерирует фейковый нерабочий ключ для вывода текста
    encoded_name = urllib.parse.quote(name)
    return f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:80?type=tcp&security=none#{encoded_name}"

def get_fresh_vless_keys() -> list:
    real_keys = []
    headers_req = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    for url in SOURCES:
        try:
            res = requests.get(url, headers=headers_req, timeout=10)
            if res.status_code != 200:
                continue
            
            raw_text = res.text
            found = re.findall(r"(vless://[^\s\r\n]+)", raw_text)
            
            for key in found:
                clean_key = key.strip()
                name = ""
                if "#" in clean_key:
                    name = urllib.parse.unquote(clean_key.split("#", 1)[1]).lower()
                
                # Жесткий фильтр: отсекаем чужой мусор и чужие каналы
                is_dummy = False
                bad_words = ["🛸", "🪐", "t.me", "wrongside", "update", "github", "127.0.0.1", "0.0.0.0"]
                
                for word in bad_words:
                    if word in name or word in clean_key.lower():
                        is_dummy = True
                        break
                
                # Если сервер прошел проверку - берем
                if not is_dummy and clean_key not in real_keys:
                    real_keys.append(clean_key)
                    
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
            continue

    print(f"Собрано реальных серверов: {len(real_keys)}")
    
    if not real_keys:
        return []
        
    # Выбираем 5 случайных рабочих серверов
    selected_real = random.sample(real_keys, min(5, len(real_keys)))
    
    # Формируем итоговый список (сначала свои пустышки, потом сервера)
    final_keys = [generate_dummy(text) for text in CUSTOM_HEADERS]
    final_keys.extend(selected_real)
    
    return final_keys

def update_gist(new_keys: list):
    if not new_keys:
        raise Exception("Не удалось получить рабочие ключи.")

    if not GIST_TOKEN:
        raise Exception("Секрет GIST_TOKEN не найден.")

    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    get_res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers, timeout=10)
    if get_res.status_code != 200:
        raise Exception(f"Ошибка доступа к Gist ({get_res.status_code})")

    gist_json = get_res.json()
    files = gist_json.get("files", {})
    filename = list(files.keys())[0]
    old_content = files[filename].get("content", "")

    is_base64 = False
    if "vless://" not in old_content and "vmess://" not in old_content:
        decoded_try = decode_base64_safely(old_content)
        if "vless://" in decoded_try:
            old_content = decoded_try
            is_base64 = True

    lines = [line.strip() for line in old_content.splitlines() if line.strip()]
    static_lines = [line for line in lines if not line.startswith("vless://")]

    updated_lines = static_lines + new_keys
    final_raw_content = "\n".join(updated_lines)

    if is_base64:
        final_payload = base64.b64encode(final_raw_content.encode("utf-8")).decode("utf-8")
    else:
        final_payload = final_raw_content

    patch_payload = {"files": {filename: {"content": final_payload}}}

    patch_res = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=patch_payload, timeout=10)
    if patch_res.status_code == 200:
        print(f"Успех! Обновлено ключей: {len(new_keys)}.")
    else:
        raise Exception(f"Ошибка записи в Gist ({patch_res.status_code})")

if __name__ == "__main__":
    fresh_keys = get_fresh_vless_keys()
    update_gist(fresh_keys)
