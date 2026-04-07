import sys
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
    Page,
    Locator,
)

CHATGPT_URL = "https://chatgpt.com/"
PROFILE_DIR = Path(".playwright_profile").resolve()


class ChatGPTWebClient:
    def __init__(self, page: Page):
        self.page = page

    def open(self) -> None:
        self.page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)

    def ensure_ready(self) -> None:
        """
        Ждём, пока на странице появится поле ввода.
        Если пользователь не залогинен, он может вручную войти в аккаунт.
        """
        if self._has_prompt_box(timeout_ms=5000):
            return

        print("\n[!] Похоже, поле ввода не найдено.")
        print("[!] Скорее всего, нужно войти в аккаунт ChatGPT вручную в открытом окне браузера.")
        input("[?] После входа нажми Enter здесь... ")

        self.page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)

        if not self._has_prompt_box(timeout_ms=15000):
            raise RuntimeError(
                "Не удалось найти поле ввода ChatGPT даже после ручного входа. "
                "Проверь, открылся ли chatgpt.com и доступен ли чат."
            )

    def send_message(self, text: str) -> None:
        box = self._get_prompt_box()
        if box is None:
            raise RuntimeError("Не удалось найти поле ввода сообщения.")

        box.click()
        box.fill(text)
        box.press("Enter")

    def get_last_assistant_message_text(self, timeout_s: int = 120) -> str:
        """
        Ждём завершения нового ответа и возвращаем текст последнего ответа ассистента.
        Логика с запасом: берём количество ответов до отправки, потом ждём, пока станет больше
        или пока последний ответ перестанет меняться.
        """
        start_time = time.time()

        previous_count = self._assistant_message_count()

        # Ждём появления нового ответа ассистента
        while time.time() - start_time < timeout_s:
            current_count = self._assistant_message_count()
            if current_count > previous_count:
                break
            self.page.wait_for_timeout(500)
        else:
            raise TimeoutError("Новый ответ ассистента не появился вовремя.")

        # Теперь ждём, пока текст перестанет меняться
        stable_rounds = 0
        last_text = ""

        while time.time() - start_time < timeout_s:
            current_text = self._read_last_assistant_message()
            if current_text and current_text == last_text:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_text = current_text

            # 4 стабильных проверки по 700 мс — обычно хватает,
            # чтобы не срезать ответ посередине.
            if current_text and stable_rounds >= 4:
                return current_text.strip()

            self.page.wait_for_timeout(700)

        if last_text.strip():
            return last_text.strip()

        raise TimeoutError("Не удалось дочитать ответ ассистента до конца.")

    def _has_prompt_box(self, timeout_ms: int = 3000) -> bool:
        try:
            box = self._get_prompt_box(timeout_ms=timeout_ms)
            return box is not None
        except Exception:
            return False

    def _get_prompt_box(self, timeout_ms: int = 3000) -> Optional[Locator]:
        """
        Пытаемся найти поле ввода максимально мягко.
        Сначала — по роли textbox, потом — запасные варианты.
        """
        candidates = [
            lambda: self.page.get_by_role("textbox"),
            lambda: self.page.locator("textarea"),
            lambda: self.page.locator("[contenteditable='true']"),
        ]

        for get_locator in candidates:
            try:
                locator = get_locator().first
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue

        return None

    def _assistant_message_count(self) -> int:
        selectors = [
            "[data-message-author-role='assistant']",
            "article",
            "[data-testid^='conversation-turn-']",
        ]

        best_count = 0
        for selector in selectors:
            try:
                count = self.page.locator(selector).count()
                if count > best_count:
                    best_count = count
            except Exception:
                continue

        return best_count

    def _read_last_assistant_message(self) -> str:
        """
        Читаем последний ответ ассистента через несколько fallback-селекторов.
        """
        selector_candidates = [
            "[data-message-author-role='assistant']",
            "[data-testid^='conversation-turn-']",
            "article",
        ]

        for selector in selector_candidates:
            try:
                locator = self.page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue

                text = locator.nth(count - 1).inner_text(timeout=3000).strip()
                if text:
                    return text
            except Exception:
                continue

        return ""


def main() -> None:
    print("=== ChatGPT Console Prototype ===")
    print("Команды:")
    print("  /exit   - выход")
    print("  /clear  - перезагрузить страницу")
    print()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )

        page = browser.pages[0] if browser.pages else browser.new_page()
        client = ChatGPTWebClient(page)

        try:
            client.open()
            client.ensure_ready()
        except Exception as e:
            browser.close()
            print(f"[X] Ошибка инициализации: {e}")
            sys.exit(1)

        print("[OK] ChatGPT открыт. Можно писать сообщения в консоль.\n")

        try:
            while True:
                user_text = input("Ты: ").strip()

                if not user_text:
                    continue

                if user_text.lower() == "/exit":
                    break

                if user_text.lower() == "/clear":
                    try:
                        client.open()
                        client.ensure_ready()
                        print("[OK] Страница перезагружена.\n")
                    except Exception as e:
                        print(f"[X] Не удалось перезагрузить страницу: {e}\n")
                    continue

                try:
                    print("[...] Отправляю сообщение...")
                    client.send_message(user_text)

                    print("[...] Жду ответ...")
                    answer = client.get_last_assistant_message_text(timeout_s=180)

                    print("\nChatGPT:")
                    print(answer)
                    print()

                except (PlaywrightTimeoutError, TimeoutError) as e:
                    print(f"[X] Таймаут: {e}\n")
                except Exception as e:
                    print(f"[X] Ошибка: {e}\n")

        finally:
            browser.close()


if __name__ == "__main__":
    main()