"""Apple Calendar service using EventKit via pyobjc.

Provides access to iCloud calendars (personal events, birthdays, holidays).
Same pattern as reminders.py.
"""

import logging
from datetime import datetime, timedelta
from threading import Event as ThreadEvent
from zoneinfo import ZoneInfo

import EventKit
import objc

logger = logging.getLogger("agent.apple_calendar")

DEFAULT_TZ = "Europe/London"


class AppleCalendarService:
    """Apple Calendar operations via EventKit."""

    def __init__(self):
        self.store = EventKit.EKEventStore.alloc().init()
        self._authorized = False

    def authorize(self) -> bool:
        """Request access to Calendar. Blocks until user responds."""
        if self._authorized:
            return True

        granted_event = ThreadEvent()
        result = {"granted": False}

        def callback(granted, error):
            result["granted"] = granted
            if error:
                logger.error(f"Calendar auth error: {error}")
            granted_event.set()

        self.store.requestFullAccessToEventsWithCompletion_(callback)
        granted_event.wait(timeout=30)

        self._authorized = result["granted"]
        if self._authorized:
            logger.info("Calendar access granted")
        else:
            logger.warning("Calendar access denied")
        return self._authorized

    def list_calendars(self) -> dict:
        """List all available calendars."""
        calendars = self.store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
        items = []
        for cal in calendars:
            source = cal.source()
            items.append({
                "id": cal.calendarIdentifier(),
                "title": cal.title(),
                "source": source.title() if source else "Unknown",
                "type": _source_type_name(source.sourceType() if source else -1),
                "editable": not cal.isImmutable(),
            })
        return {"calendars": items, "count": len(items)}

    def _find_calendar(self, name: str | None):
        """Find a calendar by name, or return the default."""
        if name is None:
            return self.store.defaultCalendarForNewEvents()

        calendars = self.store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
        for cal in calendars:
            if cal.title().lower() == name.lower():
                return cal
        return None

    def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        calendar_name: str | None = None,
        top: int = 50,
    ) -> dict:
        """List calendar events in a date range.

        Defaults to the next 7 days if no range given.
        """
        tz = ZoneInfo(DEFAULT_TZ)
        if not start:
            start = datetime.now(tz)
        if not end:
            end = start + timedelta(days=7)

        # Ensure timezone-aware
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)

        # Convert to NSDate
        ns_start = _datetime_to_nsdate(start)
        ns_end = _datetime_to_nsdate(end)

        calendars = None
        if calendar_name:
            cal = self._find_calendar(calendar_name)
            if cal:
                calendars = [cal]
            else:
                return {"error": f"Calendar '{calendar_name}' not found"}

        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            ns_start, ns_end, calendars,
        )
        events = self.store.eventsMatchingPredicate_(predicate)

        items = []
        for ev in (events or [])[:top]:
            items.append(_event_to_dict(ev))

        return {"events": items, "count": len(items)}

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        calendar_name: str | None = None,
        location: str | None = None,
        notes: str | None = None,
        is_all_day: bool = False,
        timezone_name: str = DEFAULT_TZ,
    ) -> dict:
        """Create a new calendar event."""
        calendar = self._find_calendar(calendar_name)
        if calendar is None:
            if calendar_name:
                return {"error": f"Calendar '{calendar_name}' not found"}
            return {"error": "No default calendar found"}

        if calendar.isImmutable():
            return {"error": f"Calendar '{calendar.title()}' is read-only"}

        tz = ZoneInfo(timezone_name)
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)

        event = EventKit.EKEvent.eventWithEventStore_(self.store)
        event.setTitle_(title)
        event.setStartDate_(_datetime_to_nsdate(start))
        event.setEndDate_(_datetime_to_nsdate(end))
        event.setCalendar_(calendar)
        event.setAllDay_(is_all_day)

        if location:
            event.setLocation_(location)
        if notes:
            event.setNotes_(notes)

        success = self.store.saveEvent_span_commit_error_(
            event, EventKit.EKSpanThisEvent, True, objc.nil,
        )

        if not success:
            return {"error": "Failed to save event"}

        return {
            "id": event.calendarItemIdentifier(),
            "title": event.title(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendar": calendar.title(),
            "status": "created",
        }


def _datetime_to_nsdate(dt: datetime):
    """Convert a Python datetime to an NSDate."""
    NSDate = objc.lookUpClass("NSDate")
    timestamp = dt.timestamp()
    return NSDate.dateWithTimeIntervalSince1970_(timestamp)


def _event_to_dict(ev) -> dict:
    """Convert an EKEvent to a dict."""
    start = ev.startDate()
    end = ev.endDate()
    return {
        "id": ev.calendarItemIdentifier(),
        "title": ev.title() or "(no title)",
        "start": _nsdate_to_iso(start) if start else "",
        "end": _nsdate_to_iso(end) if end else "",
        "location": ev.location() or "",
        "notes": ev.notes() or "",
        "is_all_day": bool(ev.isAllDay()),
        "calendar": ev.calendar().title() if ev.calendar() else "",
        "status": _event_status_name(ev.status()),
    }


def _nsdate_to_iso(nsdate) -> str:
    """Convert an NSDate to an ISO format string in Europe/London."""
    timestamp = nsdate.timeIntervalSince1970()
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo(DEFAULT_TZ))
    return dt.isoformat()


def _source_type_name(source_type: int) -> str:
    """Human-readable source type name."""
    names = {0: "Local", 1: "Exchange", 2: "CalDAV", 3: "MobileMe", 4: "Subscribed", 5: "Birthdays"}
    return names.get(source_type, "Other")


def _event_status_name(status: int) -> str:
    """Human-readable event status."""
    names = {0: "none", 1: "confirmed", 2: "tentative", 3: "cancelled"}
    return names.get(status, "unknown")
