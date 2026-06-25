"""Google Calendar service via Google Calendar API."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from agent.services.google_auth import GoogleAuth

logger = logging.getLogger("agent.google_calendar")

CALENDAR_URL = "https://www.googleapis.com/calendar/v3"
DEFAULT_TZ = "Europe/London"


class GoogleCalendarService:
    """Calendar operations via Google Calendar API."""

    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    async def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        top: int = 20,
    ) -> dict:
        """List calendar events in a date range.

        Defaults to the next 7 days if no range given.
        """
        headers = await self.auth.get_headers()

        if not start:
            start = datetime.now(ZoneInfo(DEFAULT_TZ))
        if not end:
            end = start + timedelta(days=7)

        # Google Calendar API requires RFC3339 timestamps
        start_str = start.isoformat()
        end_str = end.isoformat()
        # Ensure timezone info is present
        if "+" not in start_str and "Z" not in start_str:
            start_str += ZoneInfo(DEFAULT_TZ).utcoffset(start).strftime("%+03d:00") if start.tzinfo else "Z"
        if "+" not in end_str and "Z" not in end_str:
            end_str += ZoneInfo(DEFAULT_TZ).utcoffset(end).strftime("%+03d:00") if end.tzinfo else "Z"

        params = {
            "timeMin": start_str,
            "timeMax": end_str,
            "maxResults": top,
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeZone": DEFAULT_TZ,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{CALENDAR_URL}/calendars/primary/events",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        events = []
        for ev in data.get("items", []):
            start_info = ev.get("start", {})
            end_info = ev.get("end", {})
            events.append({
                "id": ev["id"],
                "subject": ev.get("summary", "(no title)"),
                "start": start_info.get("dateTime", start_info.get("date", "")),
                "end": end_info.get("dateTime", end_info.get("date", "")),
                "location": ev.get("location", ""),
                "description": ev.get("description", ""),
                "organizer": ev.get("organizer", {}).get("email", ""),
                "is_all_day": "date" in start_info and "dateTime" not in start_info,
                "status": ev.get("status", ""),
                "attendees": [
                    {
                        "email": a.get("email", ""),
                        "name": a.get("displayName", ""),
                        "status": a.get("responseStatus", ""),
                    }
                    for a in ev.get("attendees", [])
                ],
            })

        return {"events": events, "count": len(events)}

    async def create_event(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        body: str | None = None,
        attendees: list[str] | None = None,
        is_all_day: bool = False,
        timezone_name: str = DEFAULT_TZ,
    ) -> dict:
        """Create a Google Calendar event."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        if is_all_day:
            event_data = {
                "summary": subject,
                "start": {"date": start.strftime("%Y-%m-%d")},
                "end": {"date": end.strftime("%Y-%m-%d")},
            }
        else:
            event_data = {
                "summary": subject,
                "start": {
                    "dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": timezone_name,
                },
                "end": {
                    "dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": timezone_name,
                },
            }

        if location:
            event_data["location"] = location
        if body:
            event_data["description"] = body
        if attendees:
            event_data["attendees"] = [{"email": addr} for addr in attendees]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{CALENDAR_URL}/calendars/primary/events",
                headers=headers,
                json=event_data,
            )
            resp.raise_for_status()
            ev = resp.json()

        start_info = ev.get("start", {})
        return {
            "id": ev["id"],
            "subject": ev.get("summary", ""),
            "start": start_info.get("dateTime", start_info.get("date", "")),
            "status": "created",
        }
