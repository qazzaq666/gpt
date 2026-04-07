import win32com.client


def speak_text(text: str):
    speaker = win32com.client.Dispatch("SAPI.SpVoice")

    # Чуть ускорим речь (по желанию)
    speaker.Rate = 1   # можно от -5 до 5

    # Попробуем выбрать женский голос (если есть)
    voices = speaker.GetVoices()
    for i in range(voices.Count):
        v = voices.Item(i)
        desc = v.GetDescription().lower()

        if "female" in desc or "zira" in desc or "irina" in desc:
            speaker.Voice = v
            break

    speaker.Speak(text)