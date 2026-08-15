import base64
import json
import os
import requests

# Настройки
GIST_URL = os.environ.get("https://gist.githubusercontent.com/muroxe/d80e40f8efb3fcfacd9c631e12c73e1e/raw/70d8bec8fb0f9bf4e4063657db692a00134a1565/sub.txt")  # Ссылка на RAW вашего Gist
GIST_TOKEN = os.environ.get(
    "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"
)  # Токен GitHub с правами на запись в Gist
GIST_ID = os.environ.get("d80e40f8efb3fcfacd9c631e12c73e1e")  # ID вашего Gist
CHECKER_JSON = "https://tiagorrg.github.io/vless-checker/keys.json"


def get_fresh_keys():
  try:
    response = requests.get(CHECKER_JSON)
    data = response.json()
    # Извлекаем список ключей (в зависимости от структуры keys.json)
    # Обычно это список строк vless:// или объектов с полем config/link
    keys = []
    items = data.get("keys", data) if isinstance(data, dict) else data
    for item in items:
      if isinstance(item, str) and item.startswith("vless://"):
        keys.append(item)
      elif isinstance(item, dict):
        link = item.get("link") or item.get("config") or item.get("url")
        if link and link.startswith("vless://"):
          keys.append(link)

    print(f"Найдено ключей с чекера: {len(keys)}")
    return keys[:3]  # Берем первые 3 рабочих ключа
  except Exception as e:
    print(f"Ошибка при получении ключей с чекера: {e}")
    return []


def update_gist(new_keys):
  if not new_keys:
    print("Нет новых ключей для обновления.")
    return

  headers = {
      "Authorization": f"token {GIST_TOKEN}",
      "Accept": "application/vnd.github.v3+json",
  }

  # Получаем текущее содержимое Gist
  r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
  if r.status_code != 200:
    print(f"Ошибка получения Gist: {r.status_code}")
    return

  gist_data = r.json()
  filename = list(gist_data["files"].keys())[0]
  old_content = gist_data["files"][filename]["content"]

  # Декодируем, если подписка в Base64 (обычно подписки хранятся в Base64)
  try:
    decoded_bytes = base64.b64decode(
        old_content + "==="
    )  # на случай неполного padding
    decoded_text = decoded_bytes.decode("utf-8")
    is_base64 = True
  except Exception:
    decoded_text = old_content
    is_base64 = False

  # Логика замены: допустим, мы хотим заменить старые vless строки на новые
  # Или просто перезаписать определенные строки, либо добавить их в конец.
  # Самый простой способ — оставить постоянные конфиги, а блок с динамическими заменить.
  lines = decoded_text.splitlines()
  filtered_lines = [
      line for line in lines if not line.startswith("vless://")
  ]  # Удаляем старые vless

  # Добавляем новые свежие ключи
  updated_lines = filtered_lines + new_keys
  final_text = "\n".join(updated_lines)

  # Если оригинал был в base64, кодируем обратно
  if is_base64:
    payload_content = base64.b64encode(final_text.encode("utf-8")).decode(
        "utf-8"
    )
  else:
    payload_content = final_text

  # Отправляем обновленный Gist
  update_payload = {"files": {filename: {"content": payload_content}}}
  update_r = requests.patch(
      f"https://api.github.com/gists/{GIST_ID}",
      headers=headers,
      json=update_payload,
  )

  if update_r.status_code == 200:
    print("Подписка успешно обновлена!")
  else:
    print(f"Ошибка обновления Gist: {update_r.status_code} - {update_r.text}")


if __name__ == "__main__":
  new_keys = get_fresh_keys()
  update_gist(new_keys)
