"""Apple Notes service via AppleScript/osascript."""

import html
import json
import logging
import re
import subprocess

logger = logging.getLogger("agent.notes")


def _run_applescript(script: str) -> str:
    """Run an AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    return result.stdout.strip()


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode entities for plain-text output."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


class NotesService:
    """Apple Notes operations via AppleScript."""

    def search_notes(self, query: str, folder: str | None = None, top: int = 20) -> dict:
        """Search notes by title or body content.

        Args:
            query: Search term (case-insensitive, matches title or body)
            folder: Optional folder name to search within
            top: Max results to return
        """
        query_escaped = query.replace('"', '\\"')

        if folder:
            folder_escaped = folder.replace('"', '\\"')
            scope = f'folder "{folder_escaped}" of default account'
        else:
            scope = "default account"

        script = f'''
        set output to ""
        set matchCount to 0
        tell application "Notes"
            set allNotes to notes of {scope}
            repeat with n in allNotes
                if matchCount >= {top} then exit repeat
                try
                    set noteTitle to name of n
                    set noteBody to plaintext of n
                    if noteTitle contains "{query_escaped}" or noteBody contains "{query_escaped}" then
                        set noteId to id of n
                        try
                            set noteFolder to name of container of n
                        on error
                            set noteFolder to "Unknown"
                        end try
                        set previewLen to length of noteBody
                        if previewLen > 200 then set previewLen to 200
                        if previewLen > 0 then
                            set notePreview to text 1 thru previewLen of noteBody
                        else
                            set notePreview to ""
                        end if
                        set output to output & noteId & "|||" & noteTitle & "|||" & noteFolder & "|||" & notePreview & linefeed
                        set matchCount to matchCount + 1
                    end if
                end try
            end repeat
        end tell
        return output
        '''

        raw = _run_applescript(script)
        notes = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|||")
            if len(parts) >= 4:
                notes.append({
                    "id": parts[0],
                    "title": parts[1],
                    "folder": parts[2],
                    "preview": parts[3],
                })

        return {"notes": notes, "count": len(notes)}

    def get_note(self, note_id: str) -> dict:
        """Get the full content of a note by ID.

        Args:
            note_id: The note ID (from search_notes)
        """
        note_id_escaped = note_id.replace('"', '\\"')

        script = f'''
        tell application "Notes"
            set n to note id "{note_id_escaped}"
            set noteTitle to name of n
            set noteBody to body of n
            set notePlain to plaintext of n
            try
                set noteFolder to name of container of n
            on error
                set noteFolder to "Unknown"
            end try
            set noteDate to modification date of n
            return noteTitle & "|||" & noteBody & "|||" & notePlain & "|||" & noteFolder & "|||" & (noteDate as string)
        end tell
        '''

        raw = _run_applescript(script)
        parts = raw.split("|||")
        if len(parts) >= 5:
            return {
                "id": note_id,
                "title": parts[0],
                "body_html": parts[1],
                "body": _strip_html(parts[1]),
                "folder": parts[3],
                "modified": parts[4],
            }
        return {"error": "Failed to parse note content"}

    def create_note(
        self,
        title: str,
        body: str,
        folder: str | None = None,
    ) -> dict:
        """Create a new Apple Note.

        Args:
            title: The note title
            body: The note body (plain text, newlines preserved)
            folder: Optional folder name (defaults to Notes)
        """
        # Build HTML body with title as heading
        body_html = f"<h1>{html.escape(title)}</h1>"
        for para in body.split("\n\n"):
            body_html += f"<p>{html.escape(para)}</p>"

        body_escaped = body_html.replace('"', '\\"')

        if folder:
            folder_escaped = folder.replace('"', '\\"')
            target = f'folder "{folder_escaped}" of default account'
        else:
            target = "default account"

        script = f'''
        tell application "Notes"
            set newNote to make new note at {target} with properties {{body:"{body_escaped}"}}
            set noteId to id of newNote
            set noteTitle to name of newNote
            try
                set noteFolder to name of container of newNote
            on error
                set noteFolder to "Notes"
            end try
            return noteId & "|||" & noteTitle & "|||" & noteFolder
        end tell
        '''

        raw = _run_applescript(script)
        parts = raw.split("|||")
        if len(parts) >= 3:
            return {
                "id": parts[0],
                "title": parts[1],
                "folder": parts[2],
                "status": "created",
            }
        return {"error": "Failed to create note"}

    def list_folders(self) -> dict:
        """List all Apple Notes folders."""
        script = '''
        set output to ""
        tell application "Notes"
            repeat with f in folders of default account
                set output to output & name of f & linefeed
            end repeat
        end tell
        return output
        '''

        raw = _run_applescript(script)
        folders = [f.strip() for f in raw.strip().split("\n") if f.strip()]
        return {"folders": folders, "count": len(folders)}
