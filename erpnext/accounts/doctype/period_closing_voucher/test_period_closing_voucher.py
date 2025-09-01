# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import unittest

import frappe
from frappe.utils import (
	today,
	now_datetime,
	add_years,
	add_days,
	add_months,
	cstr,
	flt,
	get_first_day,
	get_last_day,
	getdate,
	is_last_day_of_the_month,
	nowdate,
)

from erpnext.accounts.doctype.finance_book.test_finance_book import create_finance_book
from erpnext.accounts.doctype.journal_entry.test_journal_entry import make_journal_entry
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.accounts.utils import get_fiscal_year


class TestPeriodClosingVoucher(unittest.TestCase):
	def test_closing_entry(self):
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")

		company = create_company()
		cost_center = create_cost_center("Test Cost Center 1")

		jv1 = make_journal_entry(
			posting_date="2021-03-15",
			amount=400,
			account1="Cash - TPC",
			account2="Sales - TPC",
			cost_center=cost_center,
			save=False,
		)
		jv1.company = company
		jv1.save()
		jv1.submit()

		jv2 = make_journal_entry(
			posting_date="2021-03-15",
			amount=600,
			account1="Cost of Goods Sold - TPC",
			account2="Cash - TPC",
			cost_center=cost_center,
			save=False,
		)
		jv2.company = company
		jv2.save()
		jv2.submit()

		pcv = self.make_period_closing_voucher(posting_date="2021-03-31")
		surplus_account = pcv.closing_account_head

		expected_gle = (
			("Cost of Goods Sold - TPC", 0.0, 600.0),
			(surplus_account, 200.0, 0.0),
			("Sales - TPC", 400.0, 0.0),
		)

		pcv_gle = frappe.db.sql(
			"""
			select account, debit, credit from `tabGL Entry` where voucher_no=%s order by account
		""",
			(pcv.name),
		)
		pcv.reload()
		self.assertEqual(pcv.gle_processing_status, "Completed")
		self.assertEqual(pcv_gle, expected_gle)

	def test_cost_center_wise_posting(self):
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")

		company = create_company()
		surplus_account = create_account()

		cost_center1 = create_cost_center("Main")
		cost_center2 = create_cost_center("Western Branch")

		create_sales_invoice(
			company=company,
			cost_center=cost_center1,
			income_account="Sales - TPC",
			expense_account="Cost of Goods Sold - TPC",
			rate=400,
			debit_to="Debtors - TPC",
			currency="USD",
			customer="_Test Customer USD",
			posting_date="2021-03-15",
		)
		create_sales_invoice(
			company=company,
			cost_center=cost_center2,
			income_account="Sales - TPC",
			expense_account="Cost of Goods Sold - TPC",
			rate=200,
			debit_to="Debtors - TPC",
			currency="USD",
			customer="_Test Customer USD",
			posting_date="2021-03-15",
		)

		pcv = self.make_period_closing_voucher(posting_date="2021-03-31", submit=False)
		pcv.save()
		pcv.submit()
		surplus_account = pcv.closing_account_head

		expected_gle = (
			(surplus_account, 0.0, 400.0, cost_center1),
			(surplus_account, 0.0, 200.0, cost_center2),
			("Sales - TPC", 400.0, 0.0, cost_center1),
			("Sales - TPC", 200.0, 0.0, cost_center2),
		)

		pcv_gle = frappe.db.sql(
			"""
			select account, debit, credit, cost_center
			from `tabGL Entry` where voucher_no=%s
			order by account, cost_center
		""",
			(pcv.name),
		)

		self.assertSequenceEqual(pcv_gle, expected_gle)

		pcv.reload()
		pcv.cancel()

		self.assertFalse(
			frappe.db.get_value(
				"GL Entry",
				{"voucher_type": "Period Closing Voucher", "voucher_no": pcv.name, "is_cancelled": 0},
			)
		)

	def test_period_closing_with_finance_book_entries(self):
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")

		company = create_company()
		surplus_account = create_account()
		cost_center = create_cost_center("Test Cost Center 1")

		create_sales_invoice(
			company=company,
			income_account="Sales - TPC",
			expense_account="Cost of Goods Sold - TPC",
			cost_center=cost_center,
			rate=400,
			debit_to="Debtors - TPC",
			currency="USD",
			customer="_Test Customer USD",
			posting_date="2021-03-15",
		)

		jv = make_journal_entry(
			account1="Cash - TPC",
			account2="Sales - TPC",
			amount=400,
			cost_center=cost_center,
			posting_date="2021-03-15",
		)
		jv.company = company
		jv.finance_book = create_finance_book().name
		jv.save()
		jv.submit()

		pcv = self.make_period_closing_voucher(posting_date="2021-03-31")
		surplus_account = pcv.closing_account_head

		expected_gle = (
			(surplus_account, 0.0, 400.0, jv.finance_book),
			(surplus_account, 0.0, 400.0, None),
			("Sales - TPC", 400.0, 0.0, jv.finance_book),
			("Sales - TPC", 400.0, 0.0, None),
		)

		pcv_gle = frappe.db.sql(
			"""
			select account, debit, credit, finance_book
			from `tabGL Entry` where voucher_no=%s
			order by account, finance_book
		""",
			(pcv.name),
		)

		self.assertSequenceEqual(pcv_gle, expected_gle)

	def test_gl_entries_restrictions(self):
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")

		company = create_company()
		cost_center = create_cost_center("Test Cost Center 1")

		self.make_period_closing_voucher(posting_date="2021-03-31")

		jv1 = make_journal_entry(
			posting_date="2021-03-15",
			amount=400,
			account1="Cash - TPC",
			account2="Sales - TPC",
			cost_center=cost_center,
			save=False,
		)
		jv1.company = company
		jv1.save()

		self.assertRaises(frappe.ValidationError, jv1.submit)

	def test_closing_balance_with_dimensions_and_test_reposting_entry(self):
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabAccount Closing Balance` where company='Test PCV Company'")

		company = create_company()
		cost_center1 = create_cost_center("Test Cost Center 1")
		cost_center2 = create_cost_center("Test Cost Center 2")

		jv1 = make_journal_entry(
			posting_date="2021-03-15",
			amount=400,
			account1="Cash - TPC",
			account2="Sales - TPC",
			cost_center=cost_center1,
			save=False,
		)
		jv1.company = company
		jv1.save()
		jv1.submit()

		jv2 = make_journal_entry(
			posting_date="2021-03-15",
			amount=200,
			account1="Cash - TPC",
			account2="Sales - TPC",
			cost_center=cost_center2,
			save=False,
		)
		jv2.company = company
		jv2.save()
		jv2.submit()

		pcv1 = self.make_period_closing_voucher(posting_date="2021-03-31")

		closing_balance = frappe.db.get_value(
			"Account Closing Balance",
			{
				"account": "Sales - TPC",
				"cost_center": cost_center1,
				"period_closing_voucher": pcv1.name,
				"is_period_closing_voucher_entry": 0,
			},
			["credit", "credit_in_account_currency"],
			as_dict=1,
		)

		self.assertEqual(closing_balance.credit, 400)
		self.assertEqual(closing_balance.credit_in_account_currency, 400)

		jv3 = make_journal_entry(
			posting_date="2022-03-15",
			amount=300,
			account1="Cash - TPC",
			account2="Sales - TPC",
			cost_center=cost_center2,
			save=False,
		)

		jv3.company = company
		jv3.save()
		jv3.submit()

		pcv2 = self.make_period_closing_voucher(posting_date="2022-03-31")

		cc1_closing_balance = frappe.db.get_value(
			"Account Closing Balance",
			{
				"account": "Sales - TPC",
				"cost_center": cost_center1,
				"period_closing_voucher": pcv2.name,
				"is_period_closing_voucher_entry": 0,
			},
			["credit", "credit_in_account_currency"],
			as_dict=1,
		)

		cc2_closing_balance = frappe.db.get_value(
			"Account Closing Balance",
			{
				"account": "Sales - TPC",
				"cost_center": cost_center2,
				"period_closing_voucher": pcv2.name,
				"is_period_closing_voucher_entry": 0,
			},
			["credit", "credit_in_account_currency"],
			as_dict=1,
		)

		self.assertEqual(cc1_closing_balance.credit, 400)
		self.assertEqual(cc1_closing_balance.credit_in_account_currency, 400)
		self.assertEqual(cc2_closing_balance.credit, 500)
		self.assertEqual(cc2_closing_balance.credit_in_account_currency, 500)

		warehouse = frappe.db.get_value("Warehouse", {"company": company}, "name")

		repost_doc = frappe.get_doc(
			{
				"doctype": "Repost Item Valuation",
				"company": company,
				"posting_date": "2020-03-15",
				"based_on": "Item and Warehouse",
				"item_code": "Test Item 1",
				"warehouse": warehouse,
			}
		)

		self.assertRaises(frappe.ValidationError, repost_doc.save)

		repost_doc.posting_date = today()
		repost_doc.save()

	def test_auto_ledger_entry_for_income_and_expense_accounts_TC_ACC_089(self):
		# Cleanup
		frappe.db.sql("delete from `tabGL Entry` where company='Test PCV Company'")
		frappe.db.sql("delete from `tabPeriod Closing Voucher` where company='Test PCV Company'")
		
		# Create required data
		company = create_company()
		surplus_account = create_account()
		cost_center = create_cost_center("Main")
		backdate = add_years(nowdate(), -2)
		last_date = get_last_day(backdate)
		create_sales_invoice(
			company=company,
			cost_center=cost_center,
			income_account="Sales - TPC",
			expense_account="Cost of Goods Sold - TPC",
			rate=1000,
			debit_to="Debtors - TPC",
			currency="USD",
			customer="_Test Customer USD",
			posting_date=backdate,
		)
		
		# Create a Period Closing Voucher
		pcv = self.make_period_closing_voucher(last_date, submit=False)
		pcv.save()
		pcv.submit()
		surplus_account = pcv.closing_account_head
		
		# Fetch GL Entries created by Period Closing Voucher
		gle = frappe.db.sql(
			"""
			SELECT account, debit, credit
			FROM `tabGL Entry`
			WHERE voucher_type='Period Closing Voucher' AND voucher_no=%s
			ORDER BY account
			""",
			(pcv.name),
			as_dict=True,
		)
		# Expected entries: Surplus Account, Sales (income), and Expense accounts
		expected_gle = [
			{"account": surplus_account, "debit": 0.0, "credit": 1000.0},
			{"account": "Sales - TPC", "debit": 1000.0, "credit": 0.0},	
		]
		
		# Assert GL Entries match the expected outcome
		self.assertEqual(len(gle), len(expected_gle))
		for i, entry in enumerate(expected_gle):
			self.assertEqual(gle[i]["account"], entry["account"])
			self.assertEqual(gle[i]["debit"], entry["debit"])
			self.assertEqual(gle[i]["credit"], entry["credit"])

	def test_get_period_start_end_date_TC_ACC_361(self):
		from erpnext.accounts.doctype.period_closing_voucher.period_closing_voucher import (
			get_period_start_end_date,
		)
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_company
		from erpnext.accounts.utils import get_fiscal_year
		from erpnext.buying.doctype.purchase_order.test_purchase_order import get_or_create_fiscal_year

		company = create_company(
			company_name="_Test Period Closing Company", 
			abbr="_TPC",
			currency="INR",
			country="India"
		)
		get_or_create_fiscal_year("_Test Period Closing Company")

		fy = get_fiscal_year(company="_Test Period Closing Company")
		
		self.assertTrue(fy)
  
		start_date, end_date = get_period_start_end_date(fy.get("name"), company)
		self.assertEqual(start_date, frappe.db.get_value("Fiscal Year", fy, "year_start_date"))
		self.assertEqual(end_date, frappe.db.get_value("Fiscal Year", fy, "year_end_date"))

	def test_cancel_gl_entries_when_gle_count_above_limit_TC_ACC_362(self):
	
		pcv = frappe.get_doc(
			{
				"doctype": "Period Closing Voucher",
				"company": "_Test Company",
				"closing_account_head": "_Test Account",
				"posting_date": frappe.utils.nowdate(),
			}
		)
		pcv.name = "_Test PCV"
		pcv.get_gle_count_against_current_pcv = lambda: 5005

		# Patch frappe.enqueue and frappe.msgprint
		enqueue_calls, msgprint_calls = {}, {}
		def mock_enqueue(fn, **kwargs):
			enqueue_calls.update(kwargs)
		def mock_msgprint(msg, **kwargs):
			msgprint_calls.update({"msg": msg, **kwargs})

		orig_enqueue, orig_msgprint = frappe.enqueue, frappe.msgprint
		frappe.enqueue, frappe.msgprint = mock_enqueue, mock_msgprint

		try:
			pcv.cancel_gl_entries()
		finally:
			frappe.enqueue, frappe.msgprint = orig_enqueue, orig_msgprint

		self.assertEqual(enqueue_calls.get("voucher_type"), "Period Closing Voucher")
		self.assertEqual(enqueue_calls.get("voucher_no"), pcv.name)
		self.assertEqual(enqueue_calls.get("queue"), "long")
		self.assertTrue(enqueue_calls.get("enqueue_after_commit"))

		
		self.assertIn("cancelled in the background", msgprint_calls.get("msg"))
		self.assertTrue(msgprint_calls.get("alert"))
  
	def test_validate_start_and_end_date_invalid_cases_with_messages_TC_ACC_363(self):
		from frappe.utils import add_days, formatdate
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_company
		from erpnext.accounts.utils import get_fiscal_year
		from erpnext.buying.doctype.purchase_order.test_purchase_order import get_or_create_fiscal_year

		create_company(
			company_name="_Test Company", 
			abbr="_TC",
			currency="INR",
			country="India"
		)
		get_or_create_fiscal_year("_Test Company")
		fy = get_fiscal_year(company="_Test Company")

		pcv1 = frappe.new_doc("Period Closing Voucher")
		pcv1.fiscal_year = fy.name
		pcv1.company = "_Test Company"
		pcv1.period_start_date = add_days(fy.year_start_date, 5)  
		pcv1.period_end_date = fy.year_end_date
		with self.assertRaises(frappe.ValidationError) as cm1:
			pcv1.validate_start_and_end_date()
		self.assertIn(
			f"Period Start Date must be {formatdate(fy.year_start_date)}",
			str(cm1.exception)
		)
  
		pcv2 = frappe.new_doc("Period Closing Voucher")
		pcv2.fiscal_year = fy.name
		pcv2.company = "_Test Company"
		pcv2.period_start_date = fy.year_start_date   
		pcv2.period_end_date = add_days(fy.year_start_date, -1) 
		with self.assertRaises(frappe.ValidationError) as cm2:
			pcv2.validate_start_and_end_date()
		self.assertIn(
			"Period Start Date cannot be greater than Period End Date",
			str(cm2.exception)
		)
		
		pcv3 = frappe.new_doc("Period Closing Voucher")
		pcv3.fiscal_year = fy.name
		pcv3.company = "_Test Company"
		pcv3.period_start_date = fy.year_start_date
		pcv3.period_end_date = add_days(fy.year_end_date, 1)  # Beyond FY end
		with self.assertRaises(frappe.ValidationError) as cm3:
			pcv3.validate_start_and_end_date()
		self.assertIn(
			"Period End Date cannot be greater than Fiscal Year End Date",
			str(cm3.exception)
		)


	def make_period_closing_voucher(self, posting_date, submit=True):
		surplus_account = create_account()
		cost_center = create_cost_center("Test Cost Center 1")
		fy = get_fiscal_year(posting_date, company="Test PCV Company")
		pcv = frappe.get_doc(
			{
				"doctype": "Period Closing Voucher",
				"transaction_date": posting_date or today(),
				"period_start_date": fy[1],
				"period_end_date": fy[2],
				"company": "Test PCV Company",
				"fiscal_year": fy[0],
				"cost_center": cost_center,
				"closing_account_head": surplus_account,
				"remarks": "test",
			}
		)
		pcv.insert()
		if submit:
			pcv.submit()

		return pcv


def create_company():
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": "Test PCV Company",
			"country": "United States",
			"default_currency": "USD",
		}
	)
	try:
		company.insert(ignore_if_duplicate=True)
	except frappe.DuplicateEntryError:
		pass
	return company.name


def create_account():
	account = frappe.get_doc(
		{
			"account_name": "Reserve and Surplus",
			"is_group": 0,
			"company": "Test PCV Company",
			"root_type": "Liability",
			"report_type": "Balance Sheet",
			"account_currency": "USD",
			"parent_account": "Current Liabilities - TPC",
			"doctype": "Account",
		}
	).insert(ignore_if_duplicate=True)
	return account.name


def create_cost_center(cc_name):
	costcenter = frappe.get_doc(
		{
			"company": "Test PCV Company",
			"cost_center_name": cc_name,
			"doctype": "Cost Center",
			"parent_cost_center": "Test PCV Company - TPC",
		}
	)
	costcenter.insert(ignore_if_duplicate=True)
	return costcenter.name


test_dependencies = ["Customer", "Cost Center"]
test_records = frappe.get_test_records("Period Closing Voucher")
