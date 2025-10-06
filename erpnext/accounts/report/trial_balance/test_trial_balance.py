# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from erpnext.accounts.report.trial_balance.trial_balance import execute


class TestTrialBalance(FrappeTestCase):
	def setUp(self):
		from erpnext.accounts.doctype.account.test_account import create_account
		from erpnext.accounts.doctype.cost_center.test_cost_center import (
			create_cost_center,
		)
		from erpnext.accounts.utils import get_fiscal_year
		from erpnext.buying.doctype.purchase_order.test_purchase_order import (
			get_or_create_fiscal_year,
		)

		self.company = create_company()
		get_or_create_fiscal_year(company=self.company)
		create_cost_center(
			cost_center_name="Test Cost Center",
			company="Trial Balance Company",
			parent_cost_center="Trial Balance Company - TBC",
		)
		create_account(
			account_name="Offsetting",
			company="Trial Balance Company",
			parent_account="Temporary Accounts - TBC",
		)
		self.fiscal_year = get_fiscal_year(today(), company="Trial Balance Company")[0]
		create_accounting_dimension()

	def test_offsetting_entries_for_accounting_dimensions(self):
		"""
		Checks if Trial Balance Report is balanced when filtered using a particular Accounting Dimension
		"""
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import (
			create_sales_invoice,
		)

		frappe.db.sql(
			"delete from `tabSales Invoice` where company='Trial Balance Company'"
		)
		frappe.db.sql("delete from `tabGL Entry` where company='Trial Balance Company'")

		branch1 = frappe.new_doc("Branch")
		branch1.branch = "Location 1"
		branch1.insert(ignore_if_duplicate=True)
		branch2 = frappe.new_doc("Branch")
		branch2.branch = "Location 2"
		branch2.insert(ignore_if_duplicate=True)

		si = create_sales_invoice(
			company=self.company,
			debit_to="Debtors - TBC",
			cost_center="Test Cost Center - TBC",
			income_account="Sales - TBC",
			do_not_submit=1,
		)
		si.branch = "Location 1"
		si.items[0].branch = "Location 2"
		si.save()
		si.submit()

		filters = frappe._dict(
			{
				"company": self.company,
				"fiscal_year": self.fiscal_year,
				"branch": ["Location 1"],
			}
		)
		total_row = execute(filters)[1][-1]
		self.assertEqual(total_row["debit"], total_row["credit"])

	def tearDown(self):
		clear_dimension_defaults("Branch")
		disable_dimension()

	def test_validate_filters_with_invalid_dates(self):
		filters = frappe._dict(
			{
				"fiscal_year": self.fiscal_year,
				"from_date": "2100-01-01",
				"to_date": "2000-01-01",
				"company": self.company,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			from erpnext.accounts.report.trial_balance.trial_balance import (
				validate_filters,
			)

			validate_filters(filters)

	def test_validate_filters_adjusts_out_of_range_dates(self):
		from erpnext.accounts.report.trial_balance.trial_balance import validate_filters

		filters = frappe._dict(
			{
				"fiscal_year": self.fiscal_year,
				"from_date": "1900-01-01",
				"to_date": "2200-01-01",
				"company": self.company,
			}
		)
		validate_filters(filters)
		self.assertLessEqual(filters.from_date, filters.year_end_date)
		self.assertGreaterEqual(filters.to_date, filters.year_start_date)

	def test_get_data_no_accounts(self):
		from erpnext.accounts.report.trial_balance.trial_balance import get_data

		filters = frappe._dict(
			{"company": "No Such Company", "fiscal_year": self.fiscal_year}
		)
		self.assertIsNone(get_data(filters))

	def test_calculate_values_with_existing_gl_entries(self):
		from erpnext.accounts.report.trial_balance.trial_balance import (
			calculate_values,
			accumulate_values_into_parents,
		)
		from frappe import get_all

		accounts = frappe.get_all(
			"Account",
			filters={"company": self.company},
			fields=["name", "parent_account", "account_name", "root_type"],
		)
		for d in accounts:
			for key in [
				"opening_debit",
				"opening_credit",
				"debit",
				"credit",
				"closing_debit",
				"closing_credit",
			]:
				d[key] = 0.0

		accounts_by_name = {d["name"]: d for d in accounts}

		gl_entries_by_account = {}
		for gle in get_all(
			"GL Entry",
			filters={"company": self.company},
			fields=["account", "debit", "credit", "is_opening"],
		):
			gl_entries_by_account.setdefault(gle.account, []).append(gle)

		opening_balances = {}

		calculate_values(
			accounts, gl_entries_by_account, opening_balances, show_net_values=True
		)
		accumulate_values_into_parents(accounts, accounts_by_name)

		for d in ["Sales - TBC", "Debtors - TBC"]:
			if d in accounts_by_name:
				self.assertGreaterEqual(
					accounts_by_name[d]["closing_debit"]
					+ accounts_by_name[d]["closing_credit"],
					0,
				)

	def test_prepare_data_and_total_row(self):
		from erpnext.accounts.report.trial_balance.trial_balance import prepare_data

		accounts = [
			frappe._dict(
				{
					"name": "Cash",
					"account_name": "Cash",
					"parent_account": None,
					"indent": 0,
					"opening_debit": 100,
					"opening_credit": 0,
					"debit": 50,
					"credit": 0,
					"closing_debit": 150,
					"closing_credit": 0,
				}
			)
		]
		filters = frappe._dict(
			{"from_date": today(), "to_date": today(), "show_net_values": 0}
		)
		data = prepare_data(accounts, filters, {}, "INR")
		self.assertTrue(
			any("Total" in str(row.get("account_name", "")) for row in data)
		)

	def test_prepare_opening_closing_asset_and_liability(self):
		from erpnext.accounts.report.trial_balance.trial_balance import (
			prepare_opening_closing,
		)

		row = {
			"root_type": "Asset",
			"opening_debit": 100,
			"opening_credit": 50,
			"closing_debit": 200,
			"closing_credit": 100,
		}
		prepare_opening_closing(row)
		self.assertTrue(row["opening_debit"] >= 0)
		row["root_type"] = "Liability"
		prepare_opening_closing(row)
		self.assertTrue("closing_credit" in row)

	def test_get_columns_returns_expected_fields(self):
		from erpnext.accounts.report.trial_balance.trial_balance import get_columns

		cols = get_columns()
		self.assertTrue(any(c["fieldname"] == "account" for c in cols))

	def test_get_opening_balance_with_all_filters(self):
		from erpnext.accounts.report.trial_balance.trial_balance import (
			get_opening_balance,
		)
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import (
			create_sales_invoice,
		)
		from frappe.utils import today

		# Create a test customer
		if not frappe.db.exists("Customer", "Test Customer"):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": "Test Customer",
					"customer_type": "Company",
				}
			).insert(ignore_permissions=True)

		# Create a sales invoice (this will create GL Entries)
		si = create_sales_invoice(
			customer="Test Customer",
			company=self.company,
			posting_date=today(),
			debit_to="Debtors - TBC",
			cost_center="Test Cost Center - TBC",
			income_account="Sales - TBC",
		)

		# Prepare filters
		from erpnext.accounts.utils import get_fiscal_year

		year = get_fiscal_year(today(), company=self.company)[0]

		filters = frappe._dict(
			{
				"company": self.company,
				"from_date": today(),
				"year_start_date": today(),
				"year_end_date": today(),
				"show_unclosed_fy_pl_balances": 0,
				"presentation_currency": "INR",
				"with_period_closing_entry_for_opening": 0,
				"cost_center": None,
				"finance_book": None,
				"project": None,
				"to_fiscal_year": year,
			}
		)
	
		# Get opening balances
		result = get_opening_balance(
			doctype="GL Entry", report_type="Profit and Loss", filters=filters, accounting_dimensions=[], ignore_is_opening=1
		)
		print("result", result)
		self.assertIsInstance(result, list)
		
		if si.docstatus == 1:
			si.cancel()


def create_company(**args):
    args = frappe._dict(args)
    if not frappe.db.exists("Company", args.company_name or "Trial Balance Company"):
        company = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": args.company_name or "Trial Balance Company",
                "country": args.country or "India",
                "default_currency": args.currency or "INR",
            }
        )
        company.insert(ignore_if_duplicate=True)
        return company.name
    else:
        return frappe.db.get_value(
            "Company", args.company_name or "Trial Balance Company", "name"
        )


def create_accounting_dimension(**args):
    args = frappe._dict(args)
    document_type = args.document_type or "Branch"
    if frappe.db.exists("Accounting Dimension", document_type):
        accounting_dimension = frappe.get_doc("Accounting Dimension", document_type)
        accounting_dimension.disabled = 0
    else:
        accounting_dimension = frappe.new_doc("Accounting Dimension")
        accounting_dimension.document_type = document_type
        accounting_dimension.insert()

    accounting_dimension.set("dimension_defaults", [])
    accounting_dimension.append(
        "dimension_defaults",
        {
            "company": args.company or "Trial Balance Company",
            "automatically_post_balancing_accounting_entry": 1,
            "offsetting_account": args.offsetting_account or "Offsetting - TBC",
        },
    )
    accounting_dimension.save()


def disable_dimension(**args):
    args = frappe._dict(args)
    document_type = args.document_type or "Branch"
    dimension = frappe.get_doc("Accounting Dimension", document_type)
    dimension.disabled = 1
    dimension.save()


def clear_dimension_defaults(dimension_name):
    accounting_dimension = frappe.get_doc("Accounting Dimension", dimension_name)
    accounting_dimension.dimension_defaults = []
    accounting_dimension.save()
