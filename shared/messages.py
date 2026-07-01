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
    # Outlook Email
    SEARCH_EMAILS = "search_emails"
    GET_EMAIL = "get_email"
    GET_THREAD = "get_thread"
    CREATE_DRAFT = "create_draft"
    DRAFT_REPLY = "draft_reply"
    UPDATE_DRAFT = "update_draft"
    SEND_DRAFT = "send_draft"
    SEND_EMAIL = "send_email"
    SCHEDULE_SEND = "schedule_send"
    CANCEL_SCHEDULED_SEND = "cancel_scheduled_send"
    ARCHIVE_EMAIL = "archive_email"
    ADD_ATTACHMENT = "add_attachment"
    DOWNLOAD_ATTACHMENT = "download_attachment"
    # Outlook Calendar
    LIST_EVENTS = "list_events"
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    CANCEL_EVENT = "cancel_event"
    FIND_AVAILABLE_SLOTS = "find_available_slots"
    # Documents
    CONVERT_MD_TO_PDF = "convert_md_to_pdf"
    CONVERT_MD_TO_DOCX = "convert_md_to_docx"
    # Voice Memos
    LIST_RECORDINGS = "list_recordings"
    TRANSCRIBE_RECORDING = "transcribe_recording"
    # Apple Notes
    SEARCH_NOTES = "search_notes"
    GET_NOTE = "get_note"
    CREATE_NOTE = "create_note"
    LIST_NOTE_FOLDERS = "list_note_folders"
    # Gmail
    GMAIL_SEARCH = "gmail_search"
    GMAIL_GET_EMAIL = "gmail_get_email"
    GMAIL_GET_THREAD = "gmail_get_thread"
    GMAIL_CREATE_DRAFT = "gmail_create_draft"
    GMAIL_ARCHIVE = "gmail_archive"
    GMAIL_LIST_LABELS = "gmail_list_labels"
    # Google Calendar
    GCAL_LIST_EVENTS = "gcal_list_events"
    GCAL_CREATE_EVENT = "gcal_create_event"
    # iCloud Calendar (personal)
    ICAL_LIST_CALENDARS = "ical_list_calendars"
    ICAL_LIST_EVENTS = "ical_list_events"
    ICAL_CREATE_EVENT = "ical_create_event"
    # CBS Support (Enchant)
    CBS_LIST_TICKETS = "cbs_list_tickets"
    CBS_GET_TICKET = "cbs_get_ticket"
    CBS_CLOSE_TICKET = "cbs_close_ticket"
    # RCSC Support (Enchant)
    RCSC_LIST_TICKETS = "rcsc_list_tickets"
    RCSC_GET_TICKET = "rcsc_get_ticket"
    RCSC_CLOSE_TICKET = "rcsc_close_ticket"
    # MP Portal (Development Tasks)
    MP_LIST_PROJECTS = "mp_list_projects"
    MP_MATCH_PROJECT = "mp_match_project"
    MP_LIST_ALIASES = "mp_list_aliases"
    MP_SAVE_ALIAS = "mp_save_alias"
    MP_DELETE_ALIAS = "mp_delete_alias"
    MP_CREATE_TASK = "mp_create_task"
    MP_UPDATE_TASK_STATUS = "mp_update_task_status"
    MP_SEARCH_TASKS = "mp_search_tasks"
    MP_IN_PROGRESS_TASKS = "mp_in_progress_tasks"
    MP_MY_TASKS = "mp_my_tasks"
    MP_OVERDUE_TASKS = "mp_overdue_tasks"
    MP_RECENT_TASKS = "mp_recent_tasks"
    MP_GET_TASK = "mp_get_task"
    MP_UPDATE_TASK = "mp_update_task"
    MP_OUTSTANDING_SUMMARY = "mp_outstanding_summary"
    MP_OUTSTANDING_BY_PROJECT = "mp_outstanding_by_project"
    MP_BILLABLE_SUMMARY = "mp_billable_summary"
    MP_ACTIVITY_RECENT = "mp_activity_recent"
    MP_LIST_CUSTOMERS = "mp_list_customers"
    MP_GET_CUSTOMER = "mp_get_customer"
    MP_CREATE_CUSTOMER = "mp_create_customer"
    MP_CREATE_PROJECT = "mp_create_project"
    MP_LOG_ACTIVITY = "mp_log_activity"
    MP_LIST_ACTIVITIES = "mp_list_activities"
    # QuickBooks
    QB_LIST_COMPANIES = "qb_list_companies"
    QB_GET_COMPANY_INFO = "qb_get_company_info"
    QB_LIST_CUSTOMERS = "qb_list_customers"
    QB_GET_CUSTOMER = "qb_get_customer"
    QB_SEARCH_CUSTOMERS = "qb_search_customers"
    QB_CREATE_CUSTOMER = "qb_create_customer"
    QB_LIST_INVOICES = "qb_list_invoices"
    QB_GET_INVOICE = "qb_get_invoice"
    QB_CREATE_INVOICE = "qb_create_invoice"
    QB_LIST_PAYMENTS = "qb_list_payments"
    QB_GET_PAYMENT = "qb_get_payment"
    QB_CREATE_PAYMENT = "qb_create_payment"
    QB_LIST_BILLS = "qb_list_bills"
    QB_GET_BILL = "qb_get_bill"
    QB_CREATE_BILL = "qb_create_bill"
    QB_CREATE_EXPENSE = "qb_create_expense"
    QB_LIST_ACCOUNTS = "qb_list_accounts"
    QB_LIST_ITEMS = "qb_list_items"
    QB_GET_ITEM = "qb_get_item"
    QB_CREATE_ITEM = "qb_create_item"
    QB_LIST_TAX_CODES = "qb_list_tax_codes"
    QB_LIST_TAX_RATES = "qb_list_tax_rates"
    QB_LIST_VENDORS = "qb_list_vendors"
    QB_SEARCH_VENDORS = "qb_search_vendors"
    QB_PROFIT_AND_LOSS = "qb_profit_and_loss"
    QB_BALANCE_SHEET = "qb_balance_sheet"
    # Composite
    DAILY_BRIEF = "daily_brief"
    # System
    UPDATE_AGENT = "update_agent"
    AGENT_STATUS = "agent_status"
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


# --- Outlook Email Payloads ---

class SearchEmailsPayload(BaseModel):
    query: str = ""
    folder: str | None = None
    top: int = 10


class GetEmailPayload(BaseModel):
    message_id: str


class GetThreadPayload(BaseModel):
    conversation_id: str
    top: int = 25


class CreateDraftPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    cc: list[str] | None = None
    body_type: str = "HTML"


class DraftReplyPayload(BaseModel):
    message_id: str
    body: str
    cc: list[str] | None = None
    body_type: str = "HTML"


class UpdateDraftPayload(BaseModel):
    message_id: str
    subject: str | None = None
    body: str | None = None
    to: list[str] | None = None
    cc: list[str] | None = None
    body_type: str = "HTML"


class SendDraftPayload(BaseModel):
    message_id: str


class SendEmailPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    cc: list[str] | None = None
    body_type: str = "HTML"


class ScheduleSendPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    send_at: datetime
    cc: list[str] | None = None
    body_type: str = "HTML"


class CancelScheduledSendPayload(BaseModel):
    message_id: str


class ArchiveEmailPayload(BaseModel):
    message_id: str


class AddAttachmentPayload(BaseModel):
    message_id: str
    file_path: str
    filename: str | None = None


class DownloadAttachmentPayload(BaseModel):
    message_id: str
    attachment_index: int = 0


# --- Outlook Calendar Payloads ---

class ListEventsPayload(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    top: int = 20


class CreateEventPayload(BaseModel):
    subject: str
    start: datetime
    end: datetime
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    is_all_day: bool = False
    timezone_name: str = "Europe/London"


class UpdateEventPayload(BaseModel):
    event_id: str
    subject: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    timezone_name: str = "Europe/London"


class CancelEventPayload(BaseModel):
    event_id: str
    comment: str | None = None


class FindAvailableSlotsPayload(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: int = 30


# --- Apple Notes Payloads ---

class ConvertDocumentPayload(BaseModel):
    md_path: str
    output_path: str | None = None


class ListRecordingsPayload(BaseModel):
    date: str | None = None
    top: int = 10


class TranscribeRecordingPayload(BaseModel):
    filename: str | None = None
    date: str | None = None


class SearchNotesPayload(BaseModel):
    query: str
    folder: str | None = None
    top: int = 20


class GetNotePayload(BaseModel):
    note_id: str


class CreateNotePayload(BaseModel):
    title: str
    body: str
    folder: str | None = None
    body_is_html: bool = False


class ListNoteFoldersPayload(BaseModel):
    pass


# --- Gmail Payloads ---

class GmailSearchPayload(BaseModel):
    query: str
    max_results: int = 10


class GmailGetEmailPayload(BaseModel):
    message_id: str


class GmailGetThreadPayload(BaseModel):
    thread_id: str


class GmailCreateDraftPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    cc: list[str] | None = None
    body_type: str = "html"


class GmailArchivePayload(BaseModel):
    message_id: str


# --- Google Calendar Payloads ---

class GCalListEventsPayload(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    top: int = 20


class GCalCreateEventPayload(BaseModel):
    subject: str
    start: datetime
    end: datetime
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    is_all_day: bool = False
    timezone_name: str = "Europe/London"


# --- iCloud Calendar Payloads ---

class ICalListEventsPayload(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    calendar_name: str | None = None
    top: int = 50


class ICalCreateEventPayload(BaseModel):
    title: str
    start: datetime
    end: datetime
    calendar_name: str | None = None
    location: str | None = None
    notes: str | None = None
    is_all_day: bool = False
    timezone_name: str = "Europe/London"


# --- CBS Support (Enchant) Payloads ---

class CBSListTicketsPayload(BaseModel):
    state: str = "open"
    per_page: int = 20


class CBSGetTicketPayload(BaseModel):
    ticket_id: str


class CBSCloseTicketPayload(BaseModel):
    ticket_id: str


# --- RCSC Support (Enchant) Payloads ---

class RCSCListTicketsPayload(BaseModel):
    state: str = "open"
    per_page: int = 20


class RCSCGetTicketPayload(BaseModel):
    ticket_id: str


class RCSCCloseTicketPayload(BaseModel):
    ticket_id: str


# --- MP Portal Payloads ---

class MPMatchProjectPayload(BaseModel):
    alias: str


class MPSaveAliasPayload(BaseModel):
    project_id: int
    alias: str


class MPDeleteAliasPayload(BaseModel):
    alias_id: int


class MPCreateTaskPayload(BaseModel):
    project_id: int | None = None
    project_name: str | None = None
    title: str
    description: str | None = None
    due_date: str | None = None
    chargeable: bool = False
    estimated_hours: float | None = None


class MPUpdateTaskStatusPayload(BaseModel):
    task_id: int | None = None
    ref: str | None = None
    status: str
    chargeable: bool | None = None


class MPGetTaskPayload(BaseModel):
    task_id: int | None = None
    ref: str | None = None


class MPUpdateTaskPayload(BaseModel):
    task_id: int | None = None
    ref: str | None = None
    hours_taken: float | None = None
    production_hours: float | None = None
    customer_due_date: str | None = None
    chargeable: bool | None = None
    title: str | None = None
    description: str | None = None


class MPSearchTasksPayload(BaseModel):
    query: str


class MPListCustomersPayload(BaseModel):
    q: str | None = None


class MPGetCustomerPayload(BaseModel):
    customer_id: int


class MPCreateCustomerPayload(BaseModel):
    name: str
    company_name: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    invoice_same_as_site: bool = True
    invoice_address_line_1: str | None = None
    invoice_address_line_2: str | None = None
    invoice_city: str | None = None
    invoice_county: str | None = None
    invoice_postcode: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    notes: str | None = None


class MPCreateProjectPayload(BaseModel):
    customer_id: int
    name: str
    prefix: str
    description: str | None = None
    production_url: str | None = None
    deployment_location: str | None = None
    git_repository: str | None = None
    git_branch: str | None = None
    notes: str | None = None


class MPLogActivityPayload(BaseModel):
    customer_id: int
    title: str
    description: str | None = None
    project_id: int | None = None
    task_id: int | None = None
    source: str | None = None
    occurred_at: str | None = None


class MPListActivitiesPayload(BaseModel):
    customer_id: int | None = None
    project_id: int | None = None


# --- QuickBooks Payloads ---

class QBRealmPayload(BaseModel):
    realm_id: str


class QBListCustomersPayload(BaseModel):
    realm_id: str
    active_only: bool = True
    max_results: int = 100


class QBGetCustomerPayload(BaseModel):
    realm_id: str
    customer_id: str


class QBSearchCustomersPayload(BaseModel):
    realm_id: str
    name: str


class QBCreateCustomerPayload(BaseModel):
    realm_id: str
    display_name: str
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None


class QBListInvoicesPayload(BaseModel):
    realm_id: str
    max_results: int = 20
    status: str | None = None


class QBGetInvoicePayload(BaseModel):
    realm_id: str
    invoice_id: str


class QBCreateInvoicePayload(BaseModel):
    realm_id: str
    customer_id: str
    line_items: list[dict]
    due_date: str | None = None
    invoice_number: str | None = None
    memo: str | None = None


class QBListPaymentsPayload(BaseModel):
    realm_id: str
    max_results: int = 20


class QBGetPaymentPayload(BaseModel):
    realm_id: str
    payment_id: str


class QBCreatePaymentPayload(BaseModel):
    realm_id: str
    customer_id: str
    total_amount: float
    invoice_id: str | None = None
    payment_date: str | None = None
    payment_method: str | None = None


class QBListBillsPayload(BaseModel):
    realm_id: str
    max_results: int = 20
    unpaid_only: bool = False


class QBGetBillPayload(BaseModel):
    realm_id: str
    bill_id: str


class QBCreateBillPayload(BaseModel):
    realm_id: str
    vendor_id: str
    line_items: list[dict]
    due_date: str | None = None
    memo: str | None = None


class QBCreateExpensePayload(BaseModel):
    realm_id: str
    account_id: str
    line_items: list[dict]
    vendor_id: str | None = None
    payment_type: str = "Cash"
    memo: str | None = None
    txn_date: str | None = None


class QBListAccountsPayload(BaseModel):
    realm_id: str
    account_type: str | None = None
    max_results: int = 100


class QBListItemsPayload(BaseModel):
    realm_id: str
    max_results: int = 100


class QBGetItemPayload(BaseModel):
    realm_id: str
    item_id: str


class QBCreateItemPayload(BaseModel):
    realm_id: str
    name: str
    item_type: str = "Service"
    income_account_id: str | None = None
    expense_account_id: str | None = None
    unit_price: float | None = None
    description: str | None = None


class QBListVendorsPayload(BaseModel):
    realm_id: str
    active_only: bool = True
    max_results: int = 100


class QBSearchVendorsPayload(BaseModel):
    realm_id: str
    name: str


class QBProfitAndLossPayload(BaseModel):
    realm_id: str
    start_date: str | None = None
    end_date: str | None = None


class QBBalanceSheetPayload(BaseModel):
    realm_id: str
    report_date: str | None = None


class DailyBriefPayload(BaseModel):
    date: str | None = None  # ISO date, defaults to today
    email_to: str | None = None  # Email address to send the brief to


class UpdateAgentPayload(BaseModel):
    agent_name: str | None = None


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
    version: str | None = None
