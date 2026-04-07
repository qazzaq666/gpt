import sys
import time
from typing import List, Optional

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

from tts_player import speak_text, set_tts_mode, get_tts_mode, get_tts_modes

CHATGPT_URL = "https://chatgpt.com/"
CDP_URL = "http://127.0.0.1:9222"


def clean_answer(text: str) -> str:
    if not text:
        return ""

    prefixes = [
        "ChatGPT сказал:",
        "ChatGPT said:",
    ]

    cleaned = text.strip()

    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    return cleaned


class ChatGPTWebClient:
    def __init__(self, page: Page):
        self.page = page

    def ensure_ready(self) -> None:
        self._wait_for_prompt_box(timeout_s=30)
        self._wait_until_idle(timeout_s=120)

    def send_message(self, text: str) -> None:
        self._wait_until_idle(timeout_s=180)

        box = self._get_prompt_box()
        if box is None:
            raise RuntimeError("Не удалось найти поле ввода.")

        box.click()
        box.fill(text)
        self.page.wait_for_timeout(300)

        if not self._click_send_button():
            box.press("Enter")

        self.page.wait_for_timeout(500)

    def wait_for_new_response(self, previous_messages: List[str], timeout_s: int = 240) -> str:
        start = time.time()
        last_candidate = ""
        stable_rounds = 0
        saw_generation = False

        while time.time() - start < timeout_s:
            if self._is_generating():
                saw_generation = True

            current_messages = self._get_assistant_messages()
            new_messages = self._diff_messages(previous_messages, current_messages)
            candidate = new_messages[-1].strip() if new_messages else ""

            if candidate:
                if candidate == last_candidate:
                    stable_rounds += 1
                else:
                    last_candidate = candidate
                    stable_rounds = 0

            if (
                candidate
                and saw_generation
                and not self._is_generating()
                and stable_rounds >= 2
            ):
                return candidate

            self.page.wait_for_timeout(1000)

        if last_candidate:
            return last_candidate

        raise TimeoutError("Не удалось дождаться нового ответа от ChatGPT.")

    def get_assistant_messages(self) -> List[str]:
        return self._get_assistant_messages()

    def minimize_window(self) -> None:
        session = self.page.context.new_cdp_session(self.page)
        window_info = session.send("Browser.getWindowForTarget")
        window_id = window_info["windowId"]
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {"windowState": "minimized"},
            },
        )

    def bring_to_front(self) -> None:
        self.page.bring_to_front()

    def _get_prompt_box(self):
        selectors = [
            "textarea",
            "[contenteditable='true']",
        ]

        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.is_visible(timeout=1000):
                    return locator
            except Exception:
                pass

        return None

    def _wait_for_prompt_box(self, timeout_s: int = 30) -> None:
        start = time.time()

        while time.time() - start < timeout_s:
            if self._get_prompt_box() is not None:
                return
            self.page.wait_for_timeout(1000)

        raise RuntimeError("Поле ввода ChatGPT не появилось.")

    def _click_send_button(self) -> bool:
        selectors = [
            "button[data-testid='send-button']",
            "button[aria-label*='Send']",
            "button[aria-label*='Отправ']",
        ]

        for selector in selectors:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=700) and btn.is_enabled():
                    btn.click()
                    return True
            except Exception:
                pass

        return False

    def _is_generating(self) -> bool:
        selectors = [
            "button[data-testid='stop-button']",
            "button[aria-label*='Stop']",
            "button[aria-label*='Останов']",
        ]

        for selector in selectors:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=500):
                    return True
            except Exception:
                pass

        return False

    def _wait_until_idle(self, timeout_s: int = 120) -> None:
        start = time.time()
        stable_rounds = 0

        while time.time() - start < timeout_s:
            generating = self._is_generating()

            if not generating:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if stable_rounds >= 2:
                return

            self.page.wait_for_timeout(1000)

        raise TimeoutError("ChatGPT слишком долго не завершает генерацию.")

    def _get_assistant_messages(self) -> List[str]:
        selectors = [
            "[data-message-author-role='assistant']",
            "[data-testid^='conversation-turn-']",
            "article",
        ]

        messages: List[str] = []

        for selector in selectors:
            try:
                loc = self.page.locator(selector)
                count = loc.count()
                if count == 0:
                    continue

                temp: List[str] = []

                for i in range(count):
                    try:
                        text = loc.nth(i).inner_text(timeout=1500).strip()
                        if text and len(text) > 1:
                            temp.append(text)
                    except Exception:
                        pass

                if len(temp) > len(messages):
                    messages = temp
            except Exception:
                pass

        cleaned: List[str] = []
        prev = None

        for msg in messages:
            normalized = clean_answer(msg)
            if normalized and normalized != prev:
                cleaned.append(normalized)
            prev = normalized

        return cleaned

    @staticmethod
    def _diff_messages(old: List[str], new: List[str]) -> List[str]:
        if len(new) <= len(old):
            if new and old and new[-1] != old[-1]:
                return [new[-1]]
            return []

        return new[len(old):]


def find_existing_chatgpt_page(context) -> Optional[Page]:
    for page in context.pages:
        try:
            url = page.url or ""
            if "chatgpt.com" in url:
                return page
        except Exception:
            pass
    return None


def print_help() -> None:
    print("[OK] Подключилась к уже открытому ChatGPT.")
    print("Команды:")
    print("  /exit               - выход")
    print("  /hide               - свернуть окно Chrome")
    print("  /show               - показать вкладку")
    print("  /messages           - показать число найденных ответов")
    print("  /voice              - показать текущий TTS")
    print("  /voices             - показать все TTS")
    print("  /voice windows      - включить Windows TTS")
    print("  /voice silero       - включить Silero TTS")
    print("  /voice yandex       - включить Yandex TTS")
    print()


def attach_to_existing_chrome() -> None:
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            raise RuntimeError(
                "Не удалось подключиться к Chrome через CDP.\n"
                "Проверь, что Chrome запущен с --remote-debugging-port=9222 "
                "и --user-data-dir."
            ) from e

        if not browser.contexts:
            raise RuntimeError("У подключённого Chrome нет доступных контекстов.")

        context = browser.contexts[0]

        page = find_existing_chatgpt_page(context)
        if page is None:
            raise RuntimeError(
                "Не нашла открытую вкладку с chatgpt.com.\n"
                "Открой ChatGPT вручную в debug-Chrome и запусти скрипт ещё раз."
            )

        client = ChatGPTWebClient(page)
        client.ensure_ready()
        print_help()

        while True:
            try:
                user_text = input("Ты: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nВыход.")
                break

            if not user_text:
                continue

            if user_text.lower() == "/exit":
                break

            if user_text.lower() == "/hide":
                try:
                    client.minimize_window()
                    print("[OK] Окно Chrome свернуто.\n")
                except Exception as e:
                    print(f"[X] Не удалось свернуть окно: {e}\n")
                continue

            if user_text.lower() == "/show":
                try:
                    client.bring_to_front()
                    print("[OK] Вкладка поднята на передний план.\n")
                except Exception as e:
                    print(f"[X] Не удалось показать вкладку: {e}\n")
                continue

            if user_text.lower() == "/messages":
                try:
                    msgs = client.get_assistant_messages()
                    print(f"[OK] Найдено ответов ассистента: {len(msgs)}\n")
                except Exception as e:
                    print(f"[X] Ошибка: {e}\n")
                continue

            if user_text.lower() == "/voice":
                print(f"[OK] Текущий TTS: {get_tts_mode()}\n")
                continue

            if user_text.lower() == "/voices":
                modes = ", ".join(get_tts_modes())
                print(f"[OK] Доступные TTS: {modes}\n")
                continue

            if user_text.lower().startswith("/voice "):
                mode = user_text[7:].strip()
                try:
                    selected = set_tts_mode(mode)
                    print(f"[OK] Включён TTS: {selected}\n")
                except Exception as e:
                    print(f"[X] Не удалось переключить TTS: {e}\n")
                continue

            try:
                previous = client.get_assistant_messages()

                print("[...] Отправляю сообщение...")
                client.send_message(user_text)

                print("[...] Жду завершения ответа...")
                answer = client.wait_for_new_response(previous_messages=previous, timeout_s=240)
                answer = clean_answer(answer)

                print("\nChatGPT:")
                print(answer)
                print()

                try:
                    speak_text(answer)
                except Exception as e:
                    print(f"[TTS] Ошибка: {e}")

            except (TimeoutError, PlaywrightTimeoutError) as e:
                print(f"[X] Таймаут: {e}\n")
            except Exception as e:
                print(f"[X] Ошибка: {e}\n")


if __name__ == "__main__":
    try:
        attach_to_existing_chrome()
    except Exception as e:
        print(f"[X] {e}")
        sys.exit(1)