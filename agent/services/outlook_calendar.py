"""Outlook calendar service via Microsoft Graph API."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from agent.services.outlook_auth import OutlookAuth

logger = logging.getLogger("agent.outlook_calendar")

GRAPH_URL = "https://graph.microsoft.com/v1.0"


class OutlookCalendarService:
    """Calendar operations via Microsoft Graph."""

    def __init__(self, auth: OutlookAuth):
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
            start = datetime.now(timezone.utc)
        if not end:
            end = start + timedelta(days=7)

        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S")

        url = f"{GRAPH_URL}/me/calendarView"
        params = {
            "startDateTime": start_str,
            "endDateTime": end_str,
            "$top": str(top),
            "$select": "id,subject,start,end,location,organizer,isAllDay,isCancelled,bodyPreview,attendees",
            "$orderby": "start/dateTime asc",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        events = []
        for ev in data.get("value", []):
            events.append({
                "id": ev["id"],
                "subject": ev.get("subject", "(no subject)"),
                "start": ev.get("start", {}).get("dateTime", ""),
                "end": ev.get("end", {}).get("dateTime", ""),
                "timezone": ev.get("start", {}).get("timeZone", ""),
                "location": ev.get("location", {}).get("displayName", ""),
                "organizer": ev.get("organizer", {}).get("emailAddress", {}).get("address", ""),
                "is_all_day": ev.get("isAllDay", False),
                "is_cancelled": ev.get("isCancelled", False),
                "preview": ev.get("bodyPreview", ""),
                "attendees": [
                    {
                        "email": a["emailAddress"]["address"],
                        "name": a["emailAddress"].get("name", ""),
                        "status": a.get("status", {}).get("response", ""),
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
        timezone_name: str = "Europe/London",
    ) -> dict:
        """Create a calendar event."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        event_data = {
            "subject": subject,
            "start": {
                "dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": timezone_name,
            },
            "end": {
                "dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": timezone_name,
            },
            "isAllDay": is_all_day,
        }

        if location:
            event_data["location"] = {"displayName": location}
        if body:
            event_data["body"] = {"contentType": "HTML", "content": body}
        if attendees:
            event_data["attendees"] = [
                {
                    "emailAddress": {"address": addr},
                    "type": "required",
                }
                for addr in attendees
            ]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/events",
                headers=headers,
                json=event_data,
            )
            resp.raise_for_status()
            ev = resp.json()

        return {
            "id": ev["id"],
            "subject": ev.get("subject", ""),
            "start": ev.get("start", {}).get("dateTime", ""),
            "end": ev.get("end", {}).get("dateTime", ""),
            "status": "created",
        }

    async def update_event(
        self,
        event_id: str,
        subject: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        location: str | None = None,
        body: str | None = None,
        attendees: list[str] | None = None,
        timezone_name: str = "Europe/London",
    ) -> dict:
        """Update an existing calendar event."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        update_data = {}
        if subject is not None:
            update_data["subject"] = subject
        if start is not None:
            update_data["start"] = {
                "dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": timezone_name,
            }
        if end is not None:
            update_data["end"] = {
                "dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": timezone_name,
            }
        if location is not None:
            update_data["location"] = {"displayName": location}
        if body is not None:
            update_data["body"] = {"contentType": "HTML", "content": body}
        if attendees is not None:
            update_data["attendees"] = [
                {
                    "emailAddress": {"address": addr},
                    "type": "required",
                }
                for addr in attendees
            ]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{GRAPH_URL}/me/events/{event_id}",
                headers=headers,
                json=update_data,
            )
            resp.raise_for_status()
            ev = resp.json()

        return {
            "id": ev["id"],
            "subject": ev.get("subject", ""),
            "status": "updated",
        }

    async def cancel_event(self, event_id: str, comment: str | None = None) -> dict:
        """Cancel/delete a calendar event."""
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{GRAPH_URL}/me/events/{event_id}",
                headers=headers,
            )
            resp.raise_for_status()

        return {"id": event_id, "status": "cancelled"}

    async def find_available_slots(
        self,
        start: datetime,
        end: datetime,
        duration_minutes: int = 30,
    ) -> dict:
        """Find free time slots in a given range."""
        # Get all events in the range
        result = await self.list_events(start=start, end=end, top=50)
        events = result["events"]

        # Build list of busy periods
        busy = []
        for ev in events:
            if ev["is_cancelled"]:
                continue
            ev_start = datetime.fromisoformat(ev["start"])
            ev_end = datetime.fromisoformat(ev["end"])
            busy.append((ev_start, ev_end))

        # Sort by start time
        busy.sort(key=lambda x: x[0])

        # Find gaps
        free_slots = []
        current = start.replace(tzinfo=None) if start.tzinfo else start

        for busy_start, busy_end in busy:
            bs = busy_start.replace(tzinfo=None) if busy_start.tzinfo else busy_start
            be = busy_end.replace(tzinfo=None) if busy_end.tzinfo else busy_end

            if bs > current:
                gap_minutes = (bs - current).total_seconds() / 60
                if gap_minutes >= duration_minutes:
                    free_slots.append({
                        "start": current.isoformat(),
                        "end": bs.isoformat(),
                        "duration_minutes": int(gap_minutes),
                    })
            if be > current:
                current = be

        # Check remaining time after last event
        end_naive = end.replace(tzinfo=None) if end.tzinfo else end
        if end_naive > current:
            gap_minutes = (end_naive - current).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                free_slots.append({
                    "start": current.isoformat(),
                    "end": end_naive.isoformat(),
                    "duration_minutes": int(gap_minutes),
                })

        return {"free_slots": free_slots, "count": len(free_slots)}
