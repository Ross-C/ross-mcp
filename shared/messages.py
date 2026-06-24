"""Shared message schemas for agent-relay communication."""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from datetime import datetime


# --- Enums ---

class CommandType(str, Enum):
    CREATE_REMINDER = "create_reminder"
    LIST_REMINDERS = "list_reminders"
    COMPLETE_REMINDER = "complete_reminder"
    PING = "ping"


class Priority(int, Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 5
    HIGH = 9


class Status(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


# --- Command Payloads ---

class CreateReminderPayload(BaseModel):
    title: str
    notes: str | None = None
    due_date: datetime | None = None
    list_name: str | None = None
    priority: Priority = Priority.NONE


class ListRemindersPayload(BaseModel):
    list_name: str | None = None
    include_completed: bool = False


class CompleteReminderPayload(BaseModel):
    reminder_id: str


# --- Messages ---

class Command(BaseModel):
    """Message sent from relay to agent."""
    id: str = Field(description="Unique command ID for tracking")
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)


class Response(BaseModel):
    """Message sent from agent back to relay."""
    command_id: str = Field(description="ID of the command this responds to")
    status: Status
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentRegistration(BaseModel):
    """Sent by agent on WebSocket connect."""
    agent_name: str
    machine_name: str
    capabilities: list[CommandType]
