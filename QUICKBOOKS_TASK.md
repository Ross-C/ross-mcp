# QuickBooks Integration — In-Progress Task

## What's Done
1. **`agent/services/quickbooks_auth.py`** — OAuth2 auth with multi-company support (per realm_id tokens), browser-based login, background token refresh. Follows the GoogleAuth pattern.
2. **`agent/services/quickbooks.py`** — Full API service covering: company info, customers, invoices, payments, bills, expenses, accounts (chart of accounts), items/services, tax codes, tax rates, vendors, profit & loss, balance sheet. Async httpx, returns dicts. Follows the Gmail service pattern.
3. **`.env` on both agents** — `QB_CLIENT_ID` and `QB_CLIENT_SECRET` added (sandbox credentials). Also `QB_SANDBOX=true` needs adding.

## What's Remaining

### Deploy and connect
- Deploy relay (`fly deploy`) — messages.py changed so relay must go first
- Restart both agents (Mac Mini + MacBook) so they load new code
- Set `QB_SANDBOX=true` in agent `.env` files
- Run OAuth flow on Mac Mini to connect RCSC Consulting's QuickBooks
- Verify agents register QB capabilities via `agent_status`
- Switch to production when ready (`QB_SANDBOX=false`)

## QuickBooks Operations to Wire

| Operation | Command Type | Service Method |
|---|---|---|
| List companies | `qb_list_companies` | `list_companies()` |
| Get company info | `qb_get_company_info` | `get_company_info(realm_id)` |
| List customers | `qb_list_customers` | `list_customers(realm_id, active_only, max_results)` |
| Get customer | `qb_get_customer` | `get_customer(realm_id, customer_id)` |
| Search customers | `qb_search_customers` | `search_customers(realm_id, name)` |
| Create customer | `qb_create_customer` | `create_customer(realm_id, display_name, email, phone, company_name)` |
| List invoices | `qb_list_invoices` | `list_invoices(realm_id, max_results, status)` |
| Get invoice | `qb_get_invoice` | `get_invoice(realm_id, invoice_id)` |
| Create invoice | `qb_create_invoice` | `create_invoice(realm_id, customer_id, line_items, due_date, invoice_number, memo)` |
| List payments | `qb_list_payments` | `list_payments(realm_id, max_results)` |
| Get payment | `qb_get_payment` | `get_payment(realm_id, payment_id)` |
| Create payment | `qb_create_payment` | `create_payment(realm_id, customer_id, total_amount, invoice_id, payment_date, payment_method)` |
| List bills | `qb_list_bills` | `list_bills(realm_id, max_results, unpaid_only)` |
| Get bill | `qb_get_bill` | `get_bill(realm_id, bill_id)` |
| Create bill | `qb_create_bill` | `create_bill(realm_id, vendor_id, line_items, due_date, memo)` |
| Create expense | `qb_create_expense` | `create_expense(realm_id, account_id, line_items, vendor_id, payment_type, memo, txn_date)` |
| List accounts | `qb_list_accounts` | `list_accounts(realm_id, account_type, max_results)` |
| List items | `qb_list_items` | `list_items(realm_id, max_results)` |
| Get item | `qb_get_item` | `get_item(realm_id, item_id)` |
| Create item | `qb_create_item` | `create_item(realm_id, name, item_type, income_account_id, expense_account_id, unit_price, description)` |
| List tax codes | `qb_list_tax_codes` | `list_tax_codes(realm_id)` |
| List tax rates | `qb_list_tax_rates` | `list_tax_rates(realm_id)` |
| List vendors | `qb_list_vendors` | `list_vendors(realm_id, active_only, max_results)` |
| Search vendors | `qb_search_vendors` | `search_vendors(realm_id, name)` |
| Profit & loss | `qb_profit_and_loss` | `profit_and_loss(realm_id, start_date, end_date)` |
| Balance sheet | `qb_balance_sheet` | `balance_sheet(realm_id, report_date)` |

## Key Design Decisions
- Multi-company: every operation takes `realm_id` as first parameter
- Sandbox mode: controlled by `QB_SANDBOX=true` env var (defaults to true)
- Auth follows GoogleAuth pattern (browser popup, token persistence, background refresh)
- No sending/destructive actions without confirmation (PA confirms with Ross first)
- "Consulting" is the alias for RCSC Consulting (first company to connect)

## Important Notes
- Deploy relay BEFORE restarting agents (shared/messages.py changes)
- After deploy, run OAuth flow on Mac Mini to connect RCSC Consulting's QuickBooks
- Redirect URI in Intuit Developer Portal must be: `http://localhost:9878/callback`
