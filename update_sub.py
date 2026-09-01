import os
import re
import base64
import requests

GIST_TOKEN = os.environ.get("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")
GIST_ID = os.environ.get("GIST_ID", "d80e40f8efb3fcfacd9c631e12c73e1e")

# Источники свежих проверенных VLESS-конфигов, используемые чекером
SOURCES = [
    "https://raw.githubusercontent.com/youshandefeiyang/sub/main/vless.txt",
    "https://raw.githubusercontent.com/aiboboxx/v2rayfree/main/v2",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/peassss/vless-checker/main/sub.txt"
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

def get_fresh_vless_keys() -> list:
    keys = []
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for url in SOURCES:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            
            raw_text = res.text
            # Декодируем, если источник отдает данные в base64
            if "vless://" not in raw_text:
                decoded = decode_base64_safely(raw_text)
                if "vless://" in decoded:
                    raw_text = decoded

            # Извлекаем все валидные vless:// строки
            found = re.findall(r"(vless://[^\s\r\n]+)", raw_text)
            for key in found:
                if key not in keys:
                    keys.append(key)
            
            if len(keys) >= 3:
                break
        except Exception as e:
            print(f"Ошибка при запросе к {url}: {e}")
            continue

    print(f"Всего найдено свежих VLESS ключей: {len(keys)}")
    return keys[:3]

def update_gist(new_keys: list):
    if not new_keys:
        raise Exception("Не удалось получить ни одного рабочего ключа.")

    if not GIST_TOKEN or not GIST_ID:
        raise Exception("Отсутствует GIST_TOKEN или GIST_ID в переменных окружения.")

    headers = {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # Получаем структуру и файлы Gist
    get_res = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers, timeout=10)
    if get_res.status_code != 200:
        raise Exception(f"Ошибка получения Gist ({get_res.status_code}): {get_res.text}")

    gist_json = get_res.json()
    files = gist_json.get("files", {})
    if not files:
        raise Exception("В Gist не найдено файлов для обновления.")

    filename = list(files.keys())[0]
    old_content = files[filename].get("content", "")

    # Проверяем формат текущей подписки (Base64 или Plain text)
    is_base64 = False
    if "vless://" not in old_content and "vmess://" not in old_content:
        decoded_try = decode_base64_safely(old_content)
        if "vless://" in decoded_try or "vmess://" in decoded_try or "ss://" in decoded_try:
            old_content = decoded_try
            is_base64 = True

    # Оставляем статичные ключи (например, ваши личные или не-vless) и убираем старые авто-ключи
    lines = [line.strip() for line in old_content.splitlines() if line.strip()]
    static_lines = [line for line in lines if not line.startswith("vless://")]

    # Формируем обновленный список
    updated_lines = static_lines + new_keys
    final_raw_content = "\n".join(updated_lines)

    if is_base64:
        final_payload = base64.b64encode(final_raw_content.encode("utf-8")).decode("utf-8")
    else:
        final_payload = final_raw_content

    # Отправляем PATCH запрос на обновление Gist
    patch_payload = {
        "files": {
            filename: {
                "content": final_payload
            }
        }
    }

    patch_res = requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=headers, json=patch_payload, timeout=10)
    if patch_res.status_code == 200:
        print(f"Gist успешно обновлен! Записано {len(new_keys)} новых ключей.")
    else:
        raise Exception(f"Ошибка обновления Gist ({patch_res.status_code}): {patch_res.text}")

if __name__ == "__main__":
    fresh_keys = get_fresh_vless_keys()
    update_gist(fresh_keys)
    
