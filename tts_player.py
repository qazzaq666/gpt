import os
import tempfile
import threading
import subprocess
from typing import Literal, Optional

import requests

TTSMode = Literal["windows", "silero", "yandex"]


class TTSManager:
    def __init__(self) -> None:
        self.mode: TTSMode = "windows"

        # --- Silero lazy state ---
        self._silero_model = None
        self._silero_sample_rate = 48000
        self._silero_speaker = "xenia"
        self._silero_lock = threading.Lock()

        # --- Yandex config ---
        
        self.yandex_api_key: str = ""
        self.yandex_voice: str = "jane"
        self.yandex_emotion: str = "neutral"
        self.yandex_speed: str = "1.0"

    def set_mode(self, mode: str) -> str:
        mode = mode.strip().lower()

        if mode not in ("windows", "silero", "yandex"):
            raise ValueError("Неизвестный TTS-режим. Доступно: windows, silero, yandex")
        if mode == "yandex":
            raise RuntimeError(
                "Для использования Yandex TTS необходимо задать API-ключ. "
                "Открой tts_player.py и впиши self.yandex_api_key.")
        

        self.mode = mode  # type: ignore
        return self.mode

    def get_mode(self) -> str:
        return self.mode

    def get_available_modes(self) -> list[str]:
        return ["windows", "silero", "yandex"]

    def speak_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        if self.mode == "windows":
            self._speak_windows(text)
            return

        if self.mode == "silero":
            self._speak_silero(text)
            return

        if self.mode == "yandex":
            self._speak_yandex(text)
            return

        raise RuntimeError(f"Неподдерживаемый режим TTS: {self.mode}")

    # =========================
    # Windows TTS
    # =========================
    def _speak_windows(self, text: str) -> None:
        import win32com.client  # pywin32

        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Rate = 1

        voices = speaker.GetVoices()
        for i in range(voices.Count):
            voice = voices.Item(i)
            desc = voice.GetDescription().lower()
            if "female" in desc or "zira" in desc or "irina" in desc:
                speaker.Voice = voice
                break

        speaker.Speak(text)

    # =========================
    # Silero TTS
    # =========================
    def _load_silero(self) -> None:
        with self._silero_lock:
            if self._silero_model is not None:
                return

            import torch

            torch.set_num_threads(4)

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="v4_ru",
                trust_repo=True,
            )

            self._silero_model = model
            self._silero_sample_rate = 48000

    def _speak_silero(self, text: str) -> None:
        self._load_silero()

        import soundfile as sf

        audio = self._silero_model.apply_tts(
            text=text,
            speaker=self._silero_speaker,
            sample_rate=self._silero_sample_rate,
            put_accent=True,
            put_yo=True,
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            wav_path = tmp.name

        sf.write(wav_path, audio, self._silero_sample_rate)
        os.startfile(wav_path)

    # =========================
    # Yandex TTS
    # =========================
    def _speak_yandex(self, text: str) -> None:
        if not self.yandex_api_key.strip():
            raise RuntimeError(
                "Для Yandex TTS не задан API-ключ. "
                "Открой tts_player.py и впиши self.yandex_api_key."
            )

        url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}"
        }
        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": self.yandex_voice,
            "emotion": self.yandex_emotion,
            "speed": self.yandex_speed,
            "format": "mp3",
        }

        response = requests.post(url, headers=headers, data=data, timeout=60)

        if response.status_code != 200:
            raise RuntimeError(
                f"Yandex TTS вернул ошибку {response.status_code}: {response.text}"
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            audio_path = tmp.name
            tmp.write(response.content)

        os.startfile(audio_path)


tts = TTSManager()


def speak_text(text: str) -> None:
    tts.speak_text(text)


def set_tts_mode(mode: str) -> str:
    return tts.set_mode(mode)


def get_tts_mode() -> str:
    return tts.get_mode()


def get_tts_modes() -> list[str]:
    return tts.get_available_modes()