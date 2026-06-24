# Project Rules

## Email Drafting Style

When generating email drafts via Outlook:

- Greeting: "Hi [Name]" for one person, "Hi [Name]/[Name]" for two, "Hi all" for 3+
- Tone: conversational and direct, not corporate or formal
- Never use em dashes (—) or hyphens to join clauses. Use commas or full stops. Dashes look AI-generated.
- One thought per paragraph, keep paragraphs short
- UK date format (DD/MM/YYYY)
- Sign off: "Kind regards" then "Ross" on the next line
- Wrap body in Aptos font: `<div style="font-family:Aptos,Arial,Helvetica,sans-serif;font-size:12pt;color:rgb(0,0,0)">...</div>`
- NEVER send emails. Only create drafts.

## Document Generation

- DOCX: always use `agent/services/reference.docx` template (Calibri 11pt)
- PDF: must include `<meta charset="UTF-8">` and `--encoding UTF-8` flag for wkhtmltopdf
- Never attach .md files to emails (Outlook blocks them). Convert to PDF or DOCX first.
- Consistent PDF styling: Calibri font, A4, professional margins, page-break-inside:avoid on tables/code

## Timezone

All dates and times use Europe/London. Never use UTC unless explicitly asked.

## Default Services

- "email" / "calendar" = Outlook (Office 365)
- "Gmail" / "Google Calendar" = Google (explicitly named)

## Meeting Transcription

When transcribing meetings:
1. Ask when the meeting was (if not clear)
2. Find the recording by date in iCloud Drive/Meetings
3. Transcribe via Deepgram with speaker diarisation
4. Enrich: summary, who said what (label speakers), action points
5. Create Apple Note: "[Meeting Topic] — [DD/MM/YYYY HH:MM]"

## Apple Notes

- Format with HTML: h2 for sections, p tags, ol/ul for lists
- Space between sections with `<br>`
- Never create raw unformatted notes

## Reminders

- Always use Apple Reminders MCP tools
- If a time is given without a date and hasn't passed today, use today
- Only use tomorrow if the time has already passed
