"""Daily brief generator — gathers reminders, calendar, and tasks into a printable PDF."""

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("agent.daily_brief")

TZ = ZoneInfo("Europe/London")

BRIEF_CSS = """
@page { size: A4; margin: 1.5cm 2cm; }
body { font-family: Calibri, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 18pt; margin: 0 0 4px 0; color: #1a1a1a; }
.date { font-size: 11pt; color: #666; margin-bottom: 20px; }
h2 { font-size: 13pt; color: #fff; background: #2c3e50; padding: 6px 12px; border-radius: 4px; margin: 18px 0 8px 0; }
h2.meetings { background: #2980b9; }
h2.reminders { background: #27ae60; }
.item { display: flex; align-items: flex-start; margin: 4px 0; padding: 5px 8px; border-bottom: 1px solid #eee; }
.checkbox { width: 14px; height: 14px; border: 2px solid #999; border-radius: 2px; margin-right: 10px; margin-top: 2px; flex-shrink: 0; }
.item-content { flex: 1; }
.item-title { font-weight: 600; font-size: 10pt; }
.item-meta { font-size: 8.5pt; color: #777; margin-top: 1px; }
.time { font-weight: 600; color: #2980b9; min-width: 90px; display: inline-block; }
.priority-high { border-left: 3px solid #e74c3c; padding-left: 5px; }
.priority-medium { border-left: 3px solid #f39c12; padding-left: 5px; }
.overdue-tag { color: #c0392b; font-weight: 600; font-size: 8pt; }
.empty { color: #999; font-style: italic; padding: 8px; }
.summary { background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px 16px; margin: 12px 0 20px 0; font-size: 9.5pt; }
.summary strong { color: #2c3e50; }
.footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #ddd; font-size: 8pt; color: #aaa; text-align: center; }
"""

BRIEF_HTML = '''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<style>{css}</style>
</head><body>
<h1>Daily Brief</h1>
<div class="date">{date_display}</div>
<div class="summary">
<strong>{meeting_count}</strong> meeting{meeting_s} &nbsp;|&nbsp;
<strong>{reminder_count}</strong> reminder{reminder_s}
</div>
{sections}
<div class="footer">Generated {generated_at}</div>
</body></html>'''


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _format_time(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(TZ).strftime("%H:%M")
    except Exception:
        return iso_str[:5] if iso_str else ""


def _format_date_display(dt: datetime) -> str:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return f"{days[dt.weekday()]} {dt.strftime('%d/%m/%Y')}"


class DailyBriefService:
    def __init__(self, reminders, calendar, apple_calendar):
        self.reminders = reminders
        self.calendar = calendar
        self.apple_calendar = apple_calendar

    async def generate(self, date_str: str | None = None) -> dict:
        """Generate the daily brief PDF for the given date (defaults to today)."""
        import asyncio

        now = datetime.now(TZ)
        if date_str:
            try:
                target = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
            except ValueError:
                return {"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}
        else:
            target = now

        day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Gather data in parallel
        reminders_data = []
        events_data = []
        ical_events_data = []

        async def fetch_reminders():
            nonlocal reminders_data
            try:
                reminders_data = await asyncio.to_thread(self.reminders.list_reminders)
            except Exception as e:
                logger.warning(f"Failed to fetch reminders: {e}")

        async def fetch_events():
            nonlocal events_data
            try:
                result = await self.calendar.list_events(
                    start=day_start, end=day_end, top=50
                )
                events_data = result.get("events", []) if isinstance(result, dict) else []
            except Exception as e:
                logger.warning(f"Failed to fetch calendar events: {e}")

        async def fetch_ical_events():
            nonlocal ical_events_data
            try:
                if self.apple_calendar._authorized:
                    result = await asyncio.to_thread(
                        self.apple_calendar.list_events,
                        start=day_start, end=day_end, top=50
                    )
                    ical_events_data = result.get("events", []) if isinstance(result, dict) else []
            except Exception as e:
                logger.warning(f"Failed to fetch iCloud events: {e}")

        await asyncio.gather(
            fetch_reminders(), fetch_events(), fetch_ical_events()
        )

        # Filter reminders due today or overdue (no due date = show them too)
        today_reminders = []
        for r in reminders_data:
            due = r.get("due_date")
            if due:
                try:
                    due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                    if due_dt.date() <= target.date():
                        today_reminders.append(r)
                except Exception:
                    today_reminders.append(r)
            else:
                today_reminders.append(r)

        # Sort reminders: high priority first, then by due date
        def reminder_sort_key(r):
            p = r.get("priority", 0)
            priority_order = {9: 0, 5: 1, 1: 2, 0: 3}
            due = r.get("due_date") or "9999"
            return (priority_order.get(p, 3), due)

        today_reminders.sort(key=reminder_sort_key)

        # Merge and sort all calendar events by start time
        all_events = []
        for e in events_data:
            e["_source"] = "outlook"
            all_events.append(e)
        for e in ical_events_data:
            e["_source"] = "icloud"
            all_events.append(e)
        all_events.sort(key=lambda e: e.get("start", "") or "")

        # Build HTML sections
        sections = []

        # Meetings section
        sections.append('<h2 class="meetings">Meetings &amp; Events</h2>')
        if all_events:
            for e in all_events:
                start_time = _format_time(e.get("start"))
                end_time = _format_time(e.get("end"))
                title = e.get("subject") or e.get("title") or "Untitled"
                location = e.get("location", "")
                is_all_day = e.get("is_all_day") or e.get("isAllDay", False)
                source = e.get("_source", "")

                time_str = "All day" if is_all_day else f"{start_time} – {end_time}"
                meta_parts = []
                if location:
                    meta_parts.append(location)
                if source == "icloud":
                    meta_parts.append("Personal")
                meta = " · ".join(meta_parts)

                sections.append(f'''<div class="item">
<div class="checkbox"></div>
<div class="item-content">
<div class="item-title"><span class="time">{time_str}</span> {title}</div>
{f'<div class="item-meta">{meta}</div>' if meta else ''}
</div></div>''')
        else:
            sections.append('<div class="empty">No meetings or events today.</div>')

        # Reminders section
        sections.append('<h2 class="reminders">Reminders &amp; Tasks</h2>')
        if today_reminders:
            for r in today_reminders:
                title = r.get("title", "Untitled")
                priority = r.get("priority", 0)
                due = r.get("due_date")
                notes = r.get("notes", "")
                list_name = r.get("list_name", "")

                p_class = ""
                if priority == 9:
                    p_class = " priority-high"
                elif priority == 5:
                    p_class = " priority-medium"

                meta_parts = []
                if due:
                    due_time = _format_time(due)
                    if due_time and due_time != "00:00":
                        meta_parts.append(f"Due: {due_time}")
                    else:
                        try:
                            due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                            if due_dt.date() < target.date():
                                meta_parts.append(f'<span class="overdue-tag">OVERDUE from {due_dt.strftime("%d/%m")}</span>')
                        except Exception:
                            pass
                if list_name and list_name != "Reminders":
                    meta_parts.append(list_name)
                if notes:
                    meta_parts.append(notes[:80])
                meta = " · ".join(meta_parts)

                sections.append(f'''<div class="item{p_class}">
<div class="checkbox"></div>
<div class="item-content">
<div class="item-title">{title}</div>
{f'<div class="item-meta">{meta}</div>' if meta else ''}
</div></div>''')
        else:
            sections.append('<div class="empty">No reminders due today.</div>')

        # Build the full HTML

        html = BRIEF_HTML.format(
            css=BRIEF_CSS,
            date_display=_format_date_display(target),
            meeting_count=len(all_events),
            meeting_s=_plural(len(all_events)),
            reminder_count=len(today_reminders),
            reminder_s=_plural(len(today_reminders)),
            sections="\n".join(sections),
            generated_at=now.strftime("%H:%M on %d/%m/%Y"),
        )

        # Write HTML and convert to PDF
        date_slug = target.strftime("%d-%m-%Y")
        desktop = Path.home() / "Desktop"
        pdf_path = str(desktop / f"Daily Brief - {date_slug}.pdf")
        tmp_html = Path("/tmp/daily_brief.html")
        tmp_html.write_text(html, encoding="utf-8")

        try:
            subprocess.run(
                ["wkhtmltopdf", "--quiet", "--enable-local-file-access",
                 "--encoding", "UTF-8",
                 "--page-size", "A4",
                 "--margin-top", "15mm", "--margin-bottom", "15mm",
                 "--margin-left", "20mm", "--margin-right", "20mm",
                 str(tmp_html), pdf_path],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except FileNotFoundError:
            return {"error": "wkhtmltopdf not installed. Run: brew install wkhtmltopdf"}
        except subprocess.CalledProcessError as e:
            return {"error": f"PDF conversion failed: {e.stderr[:200]}"}

        pdf_size = Path(pdf_path).stat().st_size

        # Build text summary for voice/chat interfaces
        summary_lines = [f"Daily Brief for {_format_date_display(target)}:"]
        summary_lines.append(f"{len(all_events)} meeting{_plural(len(all_events))}, {len(today_reminders)} reminder{_plural(len(today_reminders))}.")

        if all_events:
            summary_lines.append("Meetings:")
            for e in all_events:
                start_time = _format_time(e.get("start"))
                title = e.get("subject") or e.get("title") or "Untitled"
                is_all_day = e.get("is_all_day") or e.get("isAllDay", False)
                time_str = "All day" if is_all_day else start_time
                summary_lines.append(f"  {time_str} - {title}")

        if today_reminders:
            summary_lines.append("Reminders:")
            for r in today_reminders[:5]:
                summary_lines.append(f"  - {r.get('title', 'Untitled')}")
            if len(today_reminders) > 5:
                summary_lines.append(f"  ...and {len(today_reminders) - 5} more")

        return {
            "pdf_path": pdf_path,
            "pdf_size_bytes": pdf_size,
            "summary": "\n".join(summary_lines),
            "meetings": len(all_events),
            "reminders": len(today_reminders),
            "date": target.strftime("%Y-%m-%d"),
        }
