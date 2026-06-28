"""QuickBooks Online service via REST API.

Supports: company info, customers, invoices, payments, bills, expenses,
accounts (chart of accounts), items/services, tax codes, and queries.

All operations require a realm_id (company ID). Multi-company aware.
"""

import logging
from datetime import date

import httpx

from agent.services.quickbooks_auth import QuickBooksAuth

logger = logging.getLogger("agent.quickbooks")

# Minor version for API calls (use latest stable)
MINOR_VERSION = "73"


class QuickBooksService:
    """QuickBooks Online accounting operations."""

    def __init__(self, auth: QuickBooksAuth):
        self.auth = auth

    def _url(self, realm_id: str, endpoint: str) -> str:
        """Build API URL for a given company and endpoint."""
        return f"{self.auth.api_base}/v3/company/{realm_id}/{endpoint}"

    async def _get(self, realm_id: str, endpoint: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request."""
        headers = await self.auth.get_headers(realm_id)
        all_params = {"minorversion": MINOR_VERSION}
        if params:
            all_params.update(params)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                self._url(realm_id, endpoint),
                headers=headers,
                params=all_params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, realm_id: str, endpoint: str, body: dict) -> dict:
        """Make an authenticated POST request."""
        headers = await self.auth.get_headers(realm_id)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url(realm_id, endpoint),
                headers=headers,
                params={"minorversion": MINOR_VERSION},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def _query(self, realm_id: str, query: str) -> dict:
        """Execute a QuickBooks query (SQL-like)."""
        headers = await self.auth.get_headers(realm_id)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                self._url(realm_id, "query"),
                headers=headers,
                params={"query": query, "minorversion": MINOR_VERSION},
            )
            resp.raise_for_status()
            return resp.json()

    # --- Company Info ---

    async def get_company_info(self, realm_id: str) -> dict:
        """Get company information."""
        data = await self._get(realm_id, f"companyinfo/{realm_id}")
        info = data.get("CompanyInfo", {})
        return {
            "id": info.get("Id"),
            "company_name": info.get("CompanyName"),
            "legal_name": info.get("LegalName"),
            "country": info.get("Country"),
            "email": info.get("Email", {}).get("Address"),
            "fiscal_year_start": info.get("FiscalYearStartMonth"),
            "industry_type": info.get("IndustryType"),
        }

    async def list_companies(self) -> dict:
        """List all authenticated QuickBooks companies."""
        companies = self.auth.list_companies()
        return {"companies": companies, "count": len(companies)}

    # --- Customers ---

    async def list_customers(self, realm_id: str, active_only: bool = True, max_results: int = 100) -> dict:
        """List customers."""
        where = "WHERE Active = true" if active_only else ""
        query = f"SELECT * FROM Customer {where} MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        customers = data.get("QueryResponse", {}).get("Customer", [])
        return {
            "customers": [self._format_customer(c) for c in customers],
            "count": len(customers),
        }

    async def get_customer(self, realm_id: str, customer_id: str) -> dict:
        """Get a specific customer by ID."""
        data = await self._get(realm_id, f"customer/{customer_id}")
        return self._format_customer(data.get("Customer", {}))

    async def search_customers(self, realm_id: str, name: str) -> dict:
        """Search customers by display name."""
        safe_name = name.replace("'", "\\'")
        query = f"SELECT * FROM Customer WHERE DisplayName LIKE '%{safe_name}%'"
        data = await self._query(realm_id, query)
        customers = data.get("QueryResponse", {}).get("Customer", [])
        return {
            "customers": [self._format_customer(c) for c in customers],
            "count": len(customers),
        }

    async def create_customer(self, realm_id: str, display_name: str,
                               email: str | None = None, phone: str | None = None,
                               company_name: str | None = None) -> dict:
        """Create a new customer."""
        body: dict = {"DisplayName": display_name}
        if email:
            body["PrimaryEmailAddr"] = {"Address": email}
        if phone:
            body["PrimaryPhone"] = {"FreeFormNumber": phone}
        if company_name:
            body["CompanyName"] = company_name

        data = await self._post(realm_id, "customer", body)
        return self._format_customer(data.get("Customer", {}))

    @staticmethod
    def _format_customer(c: dict) -> dict:
        """Format a customer record for output."""
        return {
            "id": c.get("Id"),
            "display_name": c.get("DisplayName"),
            "company_name": c.get("CompanyName"),
            "email": c.get("PrimaryEmailAddr", {}).get("Address") if isinstance(c.get("PrimaryEmailAddr"), dict) else None,
            "phone": c.get("PrimaryPhone", {}).get("FreeFormNumber") if isinstance(c.get("PrimaryPhone"), dict) else None,
            "balance": c.get("Balance"),
            "active": c.get("Active"),
            "currency": c.get("CurrencyRef", {}).get("value") if isinstance(c.get("CurrencyRef"), dict) else None,
        }

    # --- Invoices ---

    async def list_invoices(self, realm_id: str, max_results: int = 20,
                            status: str | None = None) -> dict:
        """List invoices, optionally filtered by status (paid/unpaid/overdue)."""
        where_parts = []
        if status == "unpaid":
            where_parts.append("Balance > '0'")
        elif status == "overdue":
            today = date.today().isoformat()
            where_parts.append(f"Balance > '0' AND DueDate < '{today}'")

        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        query = f"SELECT * FROM Invoice {where} ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        invoices = data.get("QueryResponse", {}).get("Invoice", [])
        return {
            "invoices": [self._format_invoice(inv) for inv in invoices],
            "count": len(invoices),
        }

    async def get_invoice(self, realm_id: str, invoice_id: str) -> dict:
        """Get a specific invoice by ID."""
        data = await self._get(realm_id, f"invoice/{invoice_id}")
        return self._format_invoice_detail(data.get("Invoice", {}))

    async def create_invoice(self, realm_id: str, customer_id: str,
                              line_items: list[dict],
                              due_date: str | None = None,
                              invoice_number: str | None = None,
                              memo: str | None = None) -> dict:
        """Create an invoice.

        line_items: list of dicts with keys:
            - description: str
            - amount: float
            - quantity: float (default 1)
            - item_id: str (optional, links to an Item/Service)
            - tax_code_id: str (optional, e.g. "20" for 20% VAT)
        """
        lines = []
        for i, item in enumerate(line_items, 1):
            line: dict = {
                "DetailType": "SalesItemLineDetail",
                "Amount": item.get("amount", 0),
                "Description": item.get("description", ""),
                "LineNum": i,
                "SalesItemLineDetail": {},
            }
            detail = line["SalesItemLineDetail"]
            if item.get("item_id"):
                detail["ItemRef"] = {"value": item["item_id"]}
            if item.get("quantity"):
                detail["Qty"] = item["quantity"]
                if item.get("amount") and item.get("quantity"):
                    detail["UnitPrice"] = item["amount"] / item["quantity"]
            if item.get("tax_code_id"):
                detail["TaxCodeRef"] = {"value": item["tax_code_id"]}

            lines.append(line)

        body: dict = {
            "CustomerRef": {"value": customer_id},
            "Line": lines,
        }
        if due_date:
            body["DueDate"] = due_date
        if invoice_number:
            body["DocNumber"] = invoice_number
        if memo:
            body["CustomerMemo"] = {"value": memo}

        data = await self._post(realm_id, "invoice", body)
        return self._format_invoice_detail(data.get("Invoice", {}))

    @staticmethod
    def _format_invoice(inv: dict) -> dict:
        """Format an invoice summary for list views."""
        return {
            "id": inv.get("Id"),
            "doc_number": inv.get("DocNumber"),
            "customer_name": inv.get("CustomerRef", {}).get("name"),
            "customer_id": inv.get("CustomerRef", {}).get("value"),
            "date": inv.get("TxnDate"),
            "due_date": inv.get("DueDate"),
            "total": inv.get("TotalAmt"),
            "balance": inv.get("Balance"),
            "currency": inv.get("CurrencyRef", {}).get("value") if isinstance(inv.get("CurrencyRef"), dict) else None,
            "status": "paid" if inv.get("Balance", 1) == 0 else "unpaid",
        }

    @staticmethod
    def _format_invoice_detail(inv: dict) -> dict:
        """Format a full invoice with line items."""
        lines = []
        for line in inv.get("Line", []):
            if line.get("DetailType") == "SalesItemLineDetail":
                detail = line.get("SalesItemLineDetail", {})
                lines.append({
                    "description": line.get("Description", ""),
                    "amount": line.get("Amount"),
                    "quantity": detail.get("Qty"),
                    "unit_price": detail.get("UnitPrice"),
                    "item_id": detail.get("ItemRef", {}).get("value") if isinstance(detail.get("ItemRef"), dict) else None,
                    "item_name": detail.get("ItemRef", {}).get("name") if isinstance(detail.get("ItemRef"), dict) else None,
                    "tax_code_id": detail.get("TaxCodeRef", {}).get("value") if isinstance(detail.get("TaxCodeRef"), dict) else None,
                })
            elif line.get("DetailType") == "SubTotalLineDetail":
                lines.append({
                    "description": "Subtotal",
                    "amount": line.get("Amount"),
                })

        return {
            "id": inv.get("Id"),
            "doc_number": inv.get("DocNumber"),
            "customer_name": inv.get("CustomerRef", {}).get("name"),
            "customer_id": inv.get("CustomerRef", {}).get("value"),
            "date": inv.get("TxnDate"),
            "due_date": inv.get("DueDate"),
            "total": inv.get("TotalAmt"),
            "balance": inv.get("Balance"),
            "tax_total": inv.get("TxnTaxDetail", {}).get("TotalTax"),
            "currency": inv.get("CurrencyRef", {}).get("value") if isinstance(inv.get("CurrencyRef"), dict) else None,
            "memo": inv.get("CustomerMemo", {}).get("value") if isinstance(inv.get("CustomerMemo"), dict) else None,
            "email_sent": inv.get("EmailStatus") == "EmailSent",
            "line_items": lines,
            "status": "paid" if inv.get("Balance", 1) == 0 else "unpaid",
            "sync_token": inv.get("SyncToken"),
        }

    # --- Payments ---

    async def list_payments(self, realm_id: str, max_results: int = 20) -> dict:
        """List recent payments."""
        query = f"SELECT * FROM Payment ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        payments = data.get("QueryResponse", {}).get("Payment", [])
        return {
            "payments": [self._format_payment(p) for p in payments],
            "count": len(payments),
        }

    async def get_payment(self, realm_id: str, payment_id: str) -> dict:
        """Get a specific payment by ID."""
        data = await self._get(realm_id, f"payment/{payment_id}")
        return self._format_payment(data.get("Payment", {}))

    async def create_payment(self, realm_id: str, customer_id: str,
                              total_amount: float,
                              invoice_id: str | None = None,
                              payment_date: str | None = None,
                              payment_method: str | None = None) -> dict:
        """Record a payment against a customer (and optionally an invoice)."""
        body: dict = {
            "CustomerRef": {"value": customer_id},
            "TotalAmt": total_amount,
        }
        if invoice_id:
            body["Line"] = [{
                "Amount": total_amount,
                "LinkedTxn": [{"TxnId": invoice_id, "TxnType": "Invoice"}],
            }]
        if payment_date:
            body["TxnDate"] = payment_date
        if payment_method:
            body["PaymentMethodRef"] = {"value": payment_method}

        data = await self._post(realm_id, "payment", body)
        return self._format_payment(data.get("Payment", {}))

    @staticmethod
    def _format_payment(p: dict) -> dict:
        """Format a payment record."""
        linked_invoices = []
        for line in p.get("Line", []):
            for txn in line.get("LinkedTxn", []):
                if txn.get("TxnType") == "Invoice":
                    linked_invoices.append(txn.get("TxnId"))

        return {
            "id": p.get("Id"),
            "customer_name": p.get("CustomerRef", {}).get("name"),
            "customer_id": p.get("CustomerRef", {}).get("value"),
            "date": p.get("TxnDate"),
            "total_amount": p.get("TotalAmt"),
            "currency": p.get("CurrencyRef", {}).get("value") if isinstance(p.get("CurrencyRef"), dict) else None,
            "linked_invoices": linked_invoices,
        }

    # --- Bills (Expenses from suppliers) ---

    async def list_bills(self, realm_id: str, max_results: int = 20,
                         unpaid_only: bool = False) -> dict:
        """List bills (supplier invoices)."""
        where = "WHERE Balance > '0'" if unpaid_only else ""
        query = f"SELECT * FROM Bill {where} ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        bills = data.get("QueryResponse", {}).get("Bill", [])
        return {
            "bills": [self._format_bill(b) for b in bills],
            "count": len(bills),
        }

    async def get_bill(self, realm_id: str, bill_id: str) -> dict:
        """Get a specific bill by ID."""
        data = await self._get(realm_id, f"bill/{bill_id}")
        return self._format_bill_detail(data.get("Bill", {}))

    async def create_bill(self, realm_id: str, vendor_id: str,
                           line_items: list[dict],
                           due_date: str | None = None,
                           memo: str | None = None) -> dict:
        """Create a bill (expense from a supplier).

        line_items: list of dicts with keys:
            - description: str
            - amount: float
            - account_id: str (expense account from chart of accounts)
            - tax_code_id: str (optional)
        """
        lines = []
        for i, item in enumerate(line_items, 1):
            line: dict = {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": item.get("amount", 0),
                "Description": item.get("description", ""),
                "LineNum": i,
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": item.get("account_id", "")},
                },
            }
            if item.get("tax_code_id"):
                line["AccountBasedExpenseLineDetail"]["TaxCodeRef"] = {"value": item["tax_code_id"]}
            lines.append(line)

        body: dict = {
            "VendorRef": {"value": vendor_id},
            "Line": lines,
        }
        if due_date:
            body["DueDate"] = due_date
        if memo:
            body["PrivateNote"] = memo

        data = await self._post(realm_id, "bill", body)
        return self._format_bill_detail(data.get("Bill", {}))

    @staticmethod
    def _format_bill(b: dict) -> dict:
        return {
            "id": b.get("Id"),
            "vendor_name": b.get("VendorRef", {}).get("name"),
            "vendor_id": b.get("VendorRef", {}).get("value"),
            "date": b.get("TxnDate"),
            "due_date": b.get("DueDate"),
            "total": b.get("TotalAmt"),
            "balance": b.get("Balance"),
            "status": "paid" if b.get("Balance", 1) == 0 else "unpaid",
        }

    @staticmethod
    def _format_bill_detail(b: dict) -> dict:
        lines = []
        for line in b.get("Line", []):
            if line.get("DetailType") == "AccountBasedExpenseLineDetail":
                detail = line.get("AccountBasedExpenseLineDetail", {})
                lines.append({
                    "description": line.get("Description", ""),
                    "amount": line.get("Amount"),
                    "account_id": detail.get("AccountRef", {}).get("value") if isinstance(detail.get("AccountRef"), dict) else None,
                    "account_name": detail.get("AccountRef", {}).get("name") if isinstance(detail.get("AccountRef"), dict) else None,
                    "tax_code_id": detail.get("TaxCodeRef", {}).get("value") if isinstance(detail.get("TaxCodeRef"), dict) else None,
                })
        return {
            "id": b.get("Id"),
            "vendor_name": b.get("VendorRef", {}).get("name"),
            "vendor_id": b.get("VendorRef", {}).get("value"),
            "date": b.get("TxnDate"),
            "due_date": b.get("DueDate"),
            "total": b.get("TotalAmt"),
            "balance": b.get("Balance"),
            "memo": b.get("PrivateNote"),
            "line_items": lines,
            "sync_token": b.get("SyncToken"),
        }

    # --- Expenses (Purchases) ---

    async def create_expense(self, realm_id: str, account_id: str,
                              line_items: list[dict],
                              vendor_id: str | None = None,
                              payment_type: str = "Cash",
                              memo: str | None = None,
                              txn_date: str | None = None) -> dict:
        """Create an expense (purchase).

        line_items: list of dicts with keys:
            - description: str
            - amount: float
            - expense_account_id: str (expense category account)
            - tax_code_id: str (optional)
        """
        lines = []
        for i, item in enumerate(line_items, 1):
            line: dict = {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": item.get("amount", 0),
                "Description": item.get("description", ""),
                "LineNum": i,
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": item.get("expense_account_id", "")},
                },
            }
            if item.get("tax_code_id"):
                line["AccountBasedExpenseLineDetail"]["TaxCodeRef"] = {"value": item["tax_code_id"]}
            lines.append(line)

        body: dict = {
            "AccountRef": {"value": account_id},
            "PaymentType": payment_type,
            "Line": lines,
        }
        if vendor_id:
            body["EntityRef"] = {"value": vendor_id, "type": "Vendor"}
        if memo:
            body["PrivateNote"] = memo
        if txn_date:
            body["TxnDate"] = txn_date

        data = await self._post(realm_id, "purchase", body)
        purchase = data.get("Purchase", {})
        return {
            "id": purchase.get("Id"),
            "account": purchase.get("AccountRef", {}).get("name"),
            "total": purchase.get("TotalAmt"),
            "date": purchase.get("TxnDate"),
            "payment_type": purchase.get("PaymentType"),
            "status": "created",
        }

    # --- Accounts (Chart of Accounts) ---

    async def list_accounts(self, realm_id: str, account_type: str | None = None,
                             max_results: int = 100) -> dict:
        """List accounts from the chart of accounts.

        account_type: filter by type (e.g. 'Expense', 'Income', 'Bank', 'Asset')
        """
        where = f"WHERE AccountType = '{account_type}'" if account_type else ""
        query = f"SELECT * FROM Account {where} MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        accounts = data.get("QueryResponse", {}).get("Account", [])
        return {
            "accounts": [{
                "id": a.get("Id"),
                "name": a.get("Name"),
                "full_name": a.get("FullyQualifiedName"),
                "type": a.get("AccountType"),
                "sub_type": a.get("AccountSubType"),
                "balance": a.get("CurrentBalance"),
                "active": a.get("Active"),
            } for a in accounts],
            "count": len(accounts),
        }

    # --- Items / Services ---

    async def list_items(self, realm_id: str, max_results: int = 100) -> dict:
        """List items/services (things you sell or buy)."""
        query = f"SELECT * FROM Item WHERE Active = true MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        items = data.get("QueryResponse", {}).get("Item", [])
        return {
            "items": [self._format_item(item) for item in items],
            "count": len(items),
        }

    async def get_item(self, realm_id: str, item_id: str) -> dict:
        """Get a specific item/service by ID."""
        data = await self._get(realm_id, f"item/{item_id}")
        return self._format_item(data.get("Item", {}))

    async def create_item(self, realm_id: str, name: str,
                           item_type: str = "Service",
                           income_account_id: str | None = None,
                           expense_account_id: str | None = None,
                           unit_price: float | None = None,
                           description: str | None = None) -> dict:
        """Create an item/service.

        item_type: 'Service', 'Inventory', or 'NonInventory'
        """
        body: dict = {
            "Name": name,
            "Type": item_type,
        }
        if income_account_id:
            body["IncomeAccountRef"] = {"value": income_account_id}
        if expense_account_id:
            body["ExpenseAccountRef"] = {"value": expense_account_id}
        if unit_price is not None:
            body["UnitPrice"] = unit_price
        if description:
            body["Description"] = description

        data = await self._post(realm_id, "item", body)
        return self._format_item(data.get("Item", {}))

    @staticmethod
    def _format_item(item: dict) -> dict:
        return {
            "id": item.get("Id"),
            "name": item.get("Name"),
            "type": item.get("Type"),
            "description": item.get("Description"),
            "unit_price": item.get("UnitPrice"),
            "purchase_cost": item.get("PurchaseCost"),
            "income_account": item.get("IncomeAccountRef", {}).get("name") if isinstance(item.get("IncomeAccountRef"), dict) else None,
            "expense_account": item.get("ExpenseAccountRef", {}).get("name") if isinstance(item.get("ExpenseAccountRef"), dict) else None,
            "taxable": item.get("Taxable"),
            "active": item.get("Active"),
        }

    # --- Tax Codes ---

    async def list_tax_codes(self, realm_id: str) -> dict:
        """List all tax codes (VAT rates)."""
        query = "SELECT * FROM TaxCode WHERE Active = true MAXRESULTS 100"
        data = await self._query(realm_id, query)
        codes = data.get("QueryResponse", {}).get("TaxCode", [])
        return {
            "tax_codes": [{
                "id": tc.get("Id"),
                "name": tc.get("Name"),
                "description": tc.get("Description"),
                "active": tc.get("Active"),
                "taxable": tc.get("Taxable"),
            } for tc in codes],
            "count": len(codes),
        }

    async def list_tax_rates(self, realm_id: str) -> dict:
        """List all tax rates."""
        query = "SELECT * FROM TaxRate MAXRESULTS 100"
        data = await self._query(realm_id, query)
        rates = data.get("QueryResponse", {}).get("TaxRate", [])
        return {
            "tax_rates": [{
                "id": tr.get("Id"),
                "name": tr.get("Name"),
                "description": tr.get("Description"),
                "rate_value": tr.get("RateValue"),
                "active": tr.get("Active"),
                "agency": tr.get("AgencyRef", {}).get("value") if isinstance(tr.get("AgencyRef"), dict) else None,
            } for tr in rates],
            "count": len(rates),
        }

    # --- Vendors (Suppliers) ---

    async def list_vendors(self, realm_id: str, active_only: bool = True,
                            max_results: int = 100) -> dict:
        """List vendors (suppliers)."""
        where = "WHERE Active = true" if active_only else ""
        query = f"SELECT * FROM Vendor {where} MAXRESULTS {max_results}"
        data = await self._query(realm_id, query)
        vendors = data.get("QueryResponse", {}).get("Vendor", [])
        return {
            "vendors": [{
                "id": v.get("Id"),
                "display_name": v.get("DisplayName"),
                "company_name": v.get("CompanyName"),
                "email": v.get("PrimaryEmailAddr", {}).get("Address") if isinstance(v.get("PrimaryEmailAddr"), dict) else None,
                "phone": v.get("PrimaryPhone", {}).get("FreeFormNumber") if isinstance(v.get("PrimaryPhone"), dict) else None,
                "balance": v.get("Balance"),
                "active": v.get("Active"),
            } for v in vendors],
            "count": len(vendors),
        }

    async def search_vendors(self, realm_id: str, name: str) -> dict:
        """Search vendors by display name."""
        safe_name = name.replace("'", "\\'")
        query = f"SELECT * FROM Vendor WHERE DisplayName LIKE '%{safe_name}%'"
        data = await self._query(realm_id, query)
        vendors = data.get("QueryResponse", {}).get("Vendor", [])
        return {
            "vendors": [{
                "id": v.get("Id"),
                "display_name": v.get("DisplayName"),
                "company_name": v.get("CompanyName"),
                "balance": v.get("Balance"),
                "active": v.get("Active"),
            } for v in vendors],
            "count": len(vendors),
        }

    # --- Profit & Loss Report ---

    async def profit_and_loss(self, realm_id: str,
                               start_date: str | None = None,
                               end_date: str | None = None) -> dict:
        """Get a profit and loss report summary."""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        data = await self._get(realm_id, "reports/ProfitAndLoss", params)
        report = data.get("Report", {})
        header = report.get("Header", {})

        # Extract top-level rows (Income, Expenses, Net Income)
        rows = []
        for row in report.get("Rows", {}).get("Row", []):
            summary = row.get("Summary", {})
            if summary:
                cols = summary.get("ColData", [])
                if len(cols) >= 2:
                    rows.append({
                        "label": cols[0].get("value", ""),
                        "amount": cols[1].get("value", ""),
                    })

        return {
            "report_name": header.get("ReportName"),
            "start_date": header.get("StartPeriod"),
            "end_date": header.get("EndPeriod"),
            "currency": header.get("Currency"),
            "summary": rows,
        }

    # --- Balance Sheet Report ---

    async def balance_sheet(self, realm_id: str,
                             report_date: str | None = None) -> dict:
        """Get a balance sheet report summary."""
        params = {}
        if report_date:
            params["end_date"] = report_date

        data = await self._get(realm_id, "reports/BalanceSheet", params)
        report = data.get("Report", {})
        header = report.get("Header", {})

        rows = []
        for row in report.get("Rows", {}).get("Row", []):
            summary = row.get("Summary", {})
            if summary:
                cols = summary.get("ColData", [])
                if len(cols) >= 2:
                    rows.append({
                        "label": cols[0].get("value", ""),
                        "amount": cols[1].get("value", ""),
                    })

        return {
            "report_name": header.get("ReportName"),
            "date": header.get("EndPeriod"),
            "currency": header.get("Currency"),
            "summary": rows,
        }
