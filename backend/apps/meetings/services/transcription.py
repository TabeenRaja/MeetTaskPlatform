from django.conf import settings


class DevTranscriber:
    """LABELLED DEVELOPMENT ADAPTER: does NOT process audio. Returns fixed sample text."""
    source = "dev_adapter"

    def transcribe(self, path, participants):
        a = participants[0].display_name if participants else "Ali Khan"
        b = participants[1].display_name if len(participants) > 1 else "Sara Ahmed"
        return (f"{a} will prepare the budget report by Friday. His phone number is 03001234567. "
                f"{b} will send the final version to {b.split()[0].lower()}@example.com. "
                f"We decided to move the product launch to next month. Someone should update the client, "
                f"but nobody confirmed who."), self.source


class WhisperTranscriber:
    source = "whisper"
    _model = None

    def transcribe(self, path, participants):
        import whisper  # lazy import: heavy
        if WhisperTranscriber._model is None:
            WhisperTranscriber._model = whisper.load_model(settings.WHISPER_MODEL)
        result = WhisperTranscriber._model.transcribe(path)
        text = result["text"].strip()
        if not text:
            raise RuntimeError("Whisper returned an empty transcript.")
        return text, self.source


def get_transcriber():
    return WhisperTranscriber() if settings.TRANSCRIBER == "whisper" else DevTranscriber()