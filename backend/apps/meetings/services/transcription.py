from importlib.resources import path

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
        import whisper

        if WhisperTranscriber._model is None:
            WhisperTranscriber._model = whisper.load_model(
                settings.WHISPER_MODEL
            )

        # Use only this meeting's participants.
        names = []
        for user in participants:
            name = user.get_full_name().strip() or user.username
            if name not in names:
                names.append(name)

        glossary = (
            "MeetTask, login module, authentication, authorization, "
            "PostgreSQL, Django, database configuration, deployment, "
            "test suites, software bugs, API."
        )

        prompt_parts = [
            "An English software project meeting.",
            f"Technical vocabulary: {glossary}",
        ]
        if names:
            prompt_parts.append(
                "Participant names: " + ", ".join(names) + "."
            )

        result = WhisperTranscriber._model.transcribe(
            path,
            language="en",
            task="transcribe",
            initial_prompt=" ".join(prompt_parts),
            fp16=False,
            temperature=0,
            beam_size=5,
            condition_on_previous_text=False,
        )

        text = result["text"].strip()
        if not text:
            raise RuntimeError("Whisper returned an empty transcript.")

        return text, self.source


def get_transcriber():
    return WhisperTranscriber() if settings.TRANSCRIBER == "whisper" else DevTranscriber()
