import os
import re
import base64
import random
import requests

GIST_TOKEN = os.environ.get("GIST_TOKEN")
GIST_ID = os.environ.get("GIST_ID", "d80e40f8efb3fcfacd9c631e12c73e1e")

# Прямые ссылки на RAW-файлы с проверенными VLESS конфигами
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

def is_valid_key(key: str) -> bool:
    # Отсеиваем ключи-заглушки (декоративные заголовки), которые ведут на локальный IP
    if "@127.0.0.1:" in key or "@0.0.0.0:" in key:
        return False
    return True

def get_fresh_vless_keys() -> list:
    keys = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    
    for url in SOURCES:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"Источник {url} вернул код {res.status_code}")
                continue
            
            raw_text = res.text
            found = re.findall(r"(vless://[^\s\r\n]+)", raw_text)
            
            for key in found:
                clean_key = key.strip()
                if clean_key not in keys and is_valid_key(clean_key):
                    keys.append(clean_key)
            
            print(f"Из файла {url.split('/')[-1]} получено ключей: {len(found)}")
            
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
            continue

    if not keys:
        return []

    # Берем 5 случайных ключей из всей собранной массы, чтобы не цеплять только начало файла
    selected_keys = random.sample(keys, min(5, len(keys)))
    print(f"Итого собрано уникальных ключей: {len(keys)}. Выбрано случайных для подписки: {len(selected_keys)}.")
    return selected_keys

def update_gist(new_keys: list):
    if not new_keys:
        raise Exception("Не удалось получить ни одного рабочего ключа из источников.")

    if not GIST_TOKEN:
        raise Exception("Секрет GIST_TOKEN не найден в Secrets репозитория.")

    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # Получаем структуру файлов вашего Gist
    get_res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers, timeout=10)
    if get_res.status_code != 200:
        raise Exception(f"Ошибка доступа к Gist ({get_res.status_code}): {get_res.text}")

    gist_json = get_res.json()
    files = gist_json.get("files", {})
    if not files:
        raise Exception("В Gist не найдено ни одного файла.")

    filename = list(files.keys())[0]
    old_content = files[filename].get("content", "")

    # Проверяем, зашифрован ли текущий gist в Base64
    is_base64 = False
    if "vless://" not in old_content and "vmess://" not in old_content and "ss://" not in old_content:
        decoded_try = decode_base64_safely(old_content)
        if any(proto in decoded_try for proto in ["vless://", "vmess://", "ss://", "trojan://", "hysteria2://"]):
            old_content = decoded_try
            is_base64 = True

    # Очищаем старые ключи vless и объединяем с новыми
    lines = [line.strip() for line in old_content.splitlines() if line.strip()]
    static_lines = [line for line in lines if not line.startswith("vless://")]

    updated_lines = static_lines + new_keys
    final_raw_content = "\n".join(updated_lines)

    if is_base64:
        final_payload = base64.b64encode(final_raw_content.encode("utf-8")).decode("utf-8")
    else:
        final_payload = final_raw_content

    patch_payload = {
        "files": {
            filename: {
                "content": final_payload
            }
        }
    }

    patch_res = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=patch_payload, timeout=10)
    if patch_res.status_code == 200:
        print(f"Gist успешно обновлен! Записано {len(new_keys)} свежих ключей.")
    else:
        raise Exception(f"Ошибка записи в Gist ({patch_res.status_code}): {patch_res.text}")

if __name__ == "__main__":
    fresh_keys = get_fresh_vless_keys()
    update_gist(fresh_keys)
