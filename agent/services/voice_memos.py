"""Voice memo transcription service via Deepgram API."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("agent.voice_memos")

ICLOUD_DRIVE = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
RECORDINGS_DIR = ICLOUD_DRIVE / "Meetings"
DEFAULT_TZ = ZoneInfo("Europe/London")

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class VoiceMemosService:
    """Find and transcribe voice memos from iCloud Drive."""

    def __init__(self):
        self.api_key = os.getenv("DEEPGRAM_API_KEY", "")

    def list_recordings(self, date: str | None = None, top: int = 10) -> dict:
        """List audio recordings in the Meeting Recordings folder.

        Args:
            date: Optional date filter in YYYY-MM-DD format (matches files modified on that date)
            top: Max results to return
        """
        if not RECORDINGS_DIR.exists():
            return {"error": "Meeting Recordings folder not found in iCloud Drive"}

        audio_exts = {".m4a", ".mp3", ".wav", ".caf", ".aac", ".ogg", ".mp4"}
        files = []

        for f in RECORDINGS_DIR.iterdir():
            if f.suffix.lower() in audio_exts and not f.name.startswith("."):
                stat = f.stat()
                modified = datetime.fromtimestamp(stat.st_mtime, tz=DEFAULT_TZ)

                if date:
                    if modified.strftime("%Y-%m-%d") != date:
                        continue

                size_mb = stat.st_size / (1024 * 1024)
                files.append({
                    "filename": f.name,
                    "path": str(f),
                    "modified": modified.isoformat(),
                    "size_mb": round(size_mb, 1),
                })

        # Sort newest first
        files.sort(key=lambda x: x["modified"], reverse=True)
        files = files[:top]

        return {"recordings": files, "count": len(files)}

    async def transcribe(
        self,
        filename: str | None = None,
        date: str | None = None,
    ) -> dict:
        """Transcribe a voice memo using Deepgram.

        Finds the recording by filename or by date (most recent on that date).
        Uses Deepgram Nova-2 with speaker diarization.

        Args:
            filename: Exact filename in Meeting Recordings folder
            date: Date to find the most recent recording (YYYY-MM-DD)
        """
        if not self.api_key:
            return {"error": "DEEPGRAM_API_KEY not set in .env"}

        # Find the file
        if filename:
            filepath = RECORDINGS_DIR / filename
            if not filepath.exists():
                return {"error": f"File not found: {filename}"}
        elif date:
            recordings = self.list_recordings(date=date)
            if not recordings.get("recordings"):
                return {"error": f"No recordings found for {date}"}
            filepath = Path(recordings["recordings"][0]["path"])
        else:
            # Most recent recording overall
            recordings = self.list_recordings(top=1)
            if not recordings.get("recordings"):
                return {"error": "No recordings found in Meeting Recordings folder"}
            filepath = Path(recordings["recordings"][0]["path"])

        logger.info(f"Transcribing: {filepath.name} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)")

        # Read the audio file
        audio_data = filepath.read_bytes()

        # Determine content type
        ext_to_mime = {
            ".m4a": "audio/mp4",
            ".mp4": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".caf": "audio/x-caf",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
        }
        content_type = ext_to_mime.get(filepath.suffix.lower(), "audio/mp4")

        # Call Deepgram with diarization and smart formatting
        params = {
            "model": "nova-3",
            "smart_format": "true",
            "diarize": "true",
            "punctuate": "true",
            "paragraphs": "true",
            "utterances": "true",
        }

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                DEEPGRAM_URL,
                params=params,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": content_type,
                },
                content=audio_data,
            )

            if resp.status_code != 200:
                return {"error": f"Deepgram API error {resp.status_code}: {resp.text[:200]}"}

            result = resp.json()

        # Extract the transcript
        channels = result.get("results", {}).get("channels", [])
        if not channels:
            return {"error": "No transcript returned from Deepgram"}

        # Get the full transcript
        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            return {"error": "No alternatives in Deepgram response"}

        transcript = alternatives[0].get("transcript", "")

        # Get paragraphs with speaker labels
        paragraphs_data = alternatives[0].get("paragraphs", {}).get("paragraphs", [])
        speaker_segments = []
        for para in paragraphs_data:
            speaker = para.get("speaker", 0)
            sentences = " ".join(s.get("text", "") for s in para.get("sentences", []))
            if sentences:
                speaker_segments.append({
                    "speaker": speaker,
                    "text": sentences,
                })

        # Get utterances for more granular speaker tracking
        utterances = result.get("results", {}).get("utterances", [])
        utterance_list = []
        for u in utterances:
            utterance_list.append({
                "speaker": u.get("speaker", 0),
                "text": u.get("transcript", ""),
                "start": u.get("start", 0),
                "end": u.get("end", 0),
            })

        file_modified = datetime.fromtimestamp(
            filepath.stat().st_mtime, tz=DEFAULT_TZ
        ).isoformat()

        return {
            "filename": filepath.name,
            "modified": file_modified,
            "duration_seconds": result.get("metadata", {}).get("duration", 0),
            "transcript": transcript,
            "speaker_segments": speaker_segments,
            "utterances": utterance_list,
        }
