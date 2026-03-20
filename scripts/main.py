import json
import time
import random
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

REMOTE_DEBUG_ADDR = "127.0.0.1:9222" # адрес для подключения к Chrome с remote-debugging
FILES_DIR = "files_json"
CONFIG_PATH = os.path.join(FILES_DIR, "config.json")
CONTACTS_PATH = os.path.join(FILES_DIR, "contact.json")
PROGRESS_PATH = os.path.join(FILES_DIR, "progress.json")

RECONNECT_ATTEMPTS = 5 # количество попыток переподключения к Chrome при неудаче
RECONNECT_DELAY = 5 # секунд между попытками переподключения


# утилиты для работы с файлами и JSON
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# возможные селекторы поля ввода в Telegram Web, так как интерфейс может меняться
INPUT_SELECTORS = [
    "div.input-message-input",
    "div.input-message-container div.input-content",
    "div.input-message-textarea",
    "div.textarea-container div[contenteditable='true']",
    "div[contenteditable='true']",
    "textarea",
]

def find_input_field(driver):
    for sel in INPUT_SELECTORS:
        fields = driver.find_elements(By.CSS_SELECTOR, sel)
        if fields:
            return fields[0]
    return None



# имитируем человеческие паузы и набор текста с возможными опечатками
def human_pause_short():
    time.sleep(random.uniform(0.6, 1.6))

def human_pause_long():
    time.sleep(random.uniform(1.6, 4.0))

def human_type(element, text, typo_chance=0.03):
    # Ввод текста посимвольно с случайными задержками и возможными опечатками
    for ch in text:
        time.sleep(random.uniform(0.04, 0.12))
        if random.random() < typo_chance:
            element.send_keys(random.choice("asdfghjkl"))
            time.sleep(random.uniform(0.06, 0.12))
            element.send_keys(Keys.BACKSPACE)
        try:
            element.send_keys(ch)
        except Exception:
            # Если элемент стал недоступен (например, из-за перерисовки страницы), просто пропускаем символ
            pass
    time.sleep(random.uniform(0.15, 0.35))

# хром с remote-debugging должен быть запущен заранее
def attach_to_remote_chrome():
    options = Options()
    options.add_experimental_option("debuggerAddress", REMOTE_DEBUG_ADDR)
    try:
        driver = webdriver.Chrome(options=options)
        print(f"[attach] Подключено к Chrome {REMOTE_DEBUG_ADDR}")
        return driver
    except Exception as e:
        print(f"[attach] Ошибка: {e}")
        return None
    
# при проблемах с подключением пытаемся переподключиться несколько раз с паузами
def ensure_attached_driver():
    for i in range(RECONNECT_ATTEMPTS):
        d = attach_to_remote_chrome()
        if d:
            return d
        print(f"[ensure] Попытка {i+1}, Chrome не доступен...")
        time.sleep(RECONNECT_DELAY)
    return None


# открытие чата по ссылке в новой вкладке
def open_chat_by_link_new_tab(driver, link, timeout=15):
    try:
        driver.execute_script("window.open(arguments[0], '_blank');", link)
        driver.switch_to.window(driver.window_handles[-1])

        start = time.time()
        while time.time() - start < timeout:
            if find_input_field(driver):
                return True
            time.sleep(0.3)

        print("[open_chat] ❌ Поле ввода НЕ найдено!")
        return False

    except Exception as e:
        print(f"[open_chat] Ошибка: {e}")
        return False

# отправка сообщения с попыткой найти кнопку отправки, а если её нет — отправить через Enter
def send_message(driver, text):
    try:
        field = find_input_field(driver)
        if not field:
            print("[send] ❌ Поле ввода НЕ найдено!")
            return False

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", field)
        time.sleep(0.2)

        try:
            field.click()
        except:
            driver.execute_script("arguments[0].click();", field)

        driver.execute_script("arguments[0].focus();", field)
        time.sleep(0.2)

        # ввод текста посимвольно
        human_type(field, text)

        # попытка отправить кнопкой
        send_buttons = driver.find_elements(By.CSS_SELECTOR,
            "button[aria-label='Send message'], button.tgico-send, button.btn-send"
        )
        if send_buttons:
            btn = send_buttons[0]
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.2)
            try:
                btn.click()
            except:
                driver.execute_script("arguments[0].click();", btn)

            time.sleep(0.4)
            return True

        # если кнопки нет, пробуем отправить через Enter
        try:
            field.send_keys(Keys.ENTER)
            time.sleep(0.4)
            return True
        except:
            pass

        print("[send] ❌ Сообщение НЕ отправлено")
        return False

    except Exception as e:
        print(f"[send] Ошибка: {e}")
        return False

# основная логика: загрузка данных, подключение к Chrome, итерация по контактам, открытие чата, отправка сообщения, сохранение прогресса
def main():
    if not os.path.exists(FILES_DIR):
        print(f"[main] Папка {FILES_DIR} не найдена")
        return

    config = load_json(CONFIG_PATH)
    contacts = load_json(CONTACTS_PATH)
    progress = load_json(PROGRESS_PATH)

    default_msg = config.get("default_message", "")

    driver = ensure_attached_driver()
    if not driver:
        print("[main] Chrome недоступен — убедитесь, что он запущен с remote-debugging")
        return

    main_handle = driver.current_window_handle

    print("[main] Начинаю рассылку...")

    start_index = progress.get("last_index", 0)
    if start_index >= len(contacts):
        start_index = 0
    i = start_index

    while i < len(contacts):
        c = contacts[i]
        name = c.get("name")
        link = c.get("chat_link")

        if not link:
            print(f"[main] ❌ Нет ссылки для {name}, пропуск")
            progress["last_index"] = i + 1
            save_json(PROGRESS_PATH, progress)
            i += 1
            continue

        print(f"[main] → Контакт #{i}: {name}")

        opened = open_chat_by_link_new_tab(driver, link)
        if not opened:
            print(f"[main] ❌ Не удалось открыть чат для {name}")
            progress["last_index"] = i + 1
            save_json(PROGRESS_PATH, progress)
            i += 1
            continue

        sent = send_message(driver, default_msg)
        # дождёмся небольшой паузы, чтобы Telegram обработал отправку
        time.sleep(0.6)

        # Закрываем вкладку с чатом и возвращаемся в основную
        try:
            driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            # если переключение не удалось — переключаемся на первый доступный
            if driver.window_handles:
                driver.switch_to.window(driver.window_handles[0])

        progress["last_index"] = i + 1
        save_json(PROGRESS_PATH, progress)
        human_pause_long()
        i += 1

    print("[main] Завершено")

if __name__ == "__main__":
    main()