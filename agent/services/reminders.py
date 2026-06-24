"""Apple Reminders service using EventKit via pyobjc."""

import logging
from datetime import datetime
from threading import Event

import EventKit
import objc

logger = logging.getLogger(__name__)


class RemindersService:
    def __init__(self):
        self.store = EventKit.EKEventStore.alloc().init()
        self._authorized = False

    def authorize(self) -> bool:
        """Request access to Reminders. Blocks until user responds."""
        if self._authorized:
            return True

        granted_event = Event()
        result = {"granted": False}

        def callback(granted, error):
            result["granted"] = granted
            if error:
                logger.error(f"Reminders auth error: {error}")
            granted_event.set()

        self.store.requestFullAccessToRemindersWithCompletion_(callback)
        granted_event.wait(timeout=30)

        self._authorized = result["granted"]
        if self._authorized:
            logger.info("Reminders access granted")
        else:
            logger.warning("Reminders access denied")
        return self._authorized

    def get_calendars(self) -> list[dict]:
        """Get all reminder lists."""
        calendars = self.store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
        return [
            {"id": cal.calendarIdentifier(), "title": cal.title()}
            for cal in calendars
        ]

    def _find_calendar(self, name: str | None) -> EventKit.EKCalendar | None:
        """Find a reminder list by name, or return the default."""
        if name is None:
            return self.store.defaultCalendarForNewReminders()

        calendars = self.store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
        for cal in calendars:
            if cal.title().lower() == name.lower():
                return cal
        return None

    def create_reminder(
        self,
        title: str,
        notes: str | None = None,
        due_date: datetime | None = None,
        list_name: str | None = None,
        priority: int = 0,
    ) -> dict:
        """Create a new reminder."""
        reminder = EventKit.EKReminder.reminderWithEventStore_(self.store)
        reminder.setTitle_(title)

        if notes:
            reminder.setNotes_(notes)

        if priority:
            reminder.setPriority_(priority)

        calendar = self._find_calendar(list_name)
        if calendar is None:
            if list_name:
                return {"error": f"Reminder list '{list_name}' not found"}
            return {"error": "No default reminder list found"}
        reminder.setCalendar_(calendar)

        if due_date:
            alarm = EventKit.EKAlarm.alarmWithAbsoluteDate_(due_date)
            reminder.addAlarm_(alarm)

            # Set due date components
            cal = objc.lookUpClass("NSCalendar").currentCalendar()
            units = (
                1 << 2  # Year
                | 1 << 3  # Month
                | 1 << 4  # Day
                | 1 << 5  # Hour
                | 1 << 6  # Minute
            )
            components = cal.components_fromDate_(units, due_date)
            reminder.setDueDateComponents_(components)

        error = None
        success = self.store.saveReminder_commit_error_(reminder, True, objc.nil)

        if not success:
            return {"error": f"Failed to save reminder: {error}"}

        return {
            "id": reminder.calendarItemIdentifier(),
            "title": reminder.title(),
            "list": calendar.title(),
            "due_date": due_date.isoformat() if due_date else None,
        }

    def list_reminders(
        self, list_name: str | None = None, include_completed: bool = False
    ) -> list[dict]:
        """List reminders. Blocks until fetch completes."""
        calendars = None
        if list_name:
            cal = self._find_calendar(list_name)
            if cal:
                calendars = [cal]
            else:
                return []

        predicate = self.store.predicateForRemindersInCalendars_(calendars)

        results_event = Event()
        fetched = {"reminders": []}

        def callback(reminders):
            if reminders:
                fetched["reminders"] = list(reminders)
            results_event.set()

        self.store.fetchRemindersMatchingPredicate_completion_(predicate, callback)
        results_event.wait(timeout=10)

        output = []
        for r in fetched["reminders"]:
            if not include_completed and r.isCompleted():
                continue
            due = None
            if r.dueDateComponents():
                due_date = r.dueDateComponents().date()
                if due_date:
                    due = due_date.description()

            output.append({
                "id": r.calendarItemIdentifier(),
                "title": r.title(),
                "notes": r.notes() or None,
                "completed": r.isCompleted(),
                "priority": r.priority(),
                "due_date": due,
                "list": r.calendar().title() if r.calendar() else None,
            })

        return output

    def complete_reminder(self, reminder_id: str) -> dict:
        """Mark a reminder as completed by its ID."""
        predicate = self.store.predicateForRemindersInCalendars_(None)

        results_event = Event()
        fetched = {"reminders": []}

        def callback(reminders):
            if reminders:
                fetched["reminders"] = list(reminders)
            results_event.set()

        self.store.fetchRemindersMatchingPredicate_completion_(predicate, callback)
        results_event.wait(timeout=10)

        for r in fetched["reminders"]:
            if r.calendarItemIdentifier() == reminder_id:
                r.setCompleted_(True)
                success = self.store.saveReminder_commit_error_(r, True, objc.nil)
                if success:
                    return {
                        "id": reminder_id,
                        "title": r.title(),
                        "completed": True,
                    }
                else:
                    return {"error": "Failed to save reminder"}

        return {"error": f"Reminder with id '{reminder_id}' not found"}
