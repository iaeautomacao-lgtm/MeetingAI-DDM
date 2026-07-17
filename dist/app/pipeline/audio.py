import os
import uuid
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()

AZURE_SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "brazilsouth").strip()


def transcrever(audio_path: str) -> dict:
    if not AZURE_SPEECH_KEY:
        raise RuntimeError("AZURE_SPEECH_KEY não configurada.")

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY,
        region=AZURE_SPEECH_REGION,
    )
    speech_config.speech_recognition_language = "pt-BR"
    speech_config.request_word_level_timestamps()

    audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
    transcriber = speechsdk.transcription.ConversationTranscriber(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    utterances = []
    full_text = []
    done = False

    def on_transcribed(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            utterances.append({
                "speaker": evt.result.speaker_id or "?",
                "texto": evt.result.text,
                "start_ms": int(evt.result.offset / 10000),
                "end_ms": int((evt.result.offset + evt.result.duration) / 10000),
            })
            full_text.append(evt.result.text)

    def on_done(evt):
        nonlocal done
        done = True

    transcriber.transcribed.connect(on_transcribed)
    transcriber.session_stopped.connect(on_done)
    transcriber.canceled.connect(on_done)

    transcriber.start_transcribing_async().get()

    import time
    while not done:
        time.sleep(0.5)

    transcriber.stop_transcribing_async().get()

    return {
        "transcript_id": str(uuid.uuid4()),
        "text": " ".join(full_text),
        "utterances": utterances,
        "audio_duration_ms": None,
        "status": "completed",
    }