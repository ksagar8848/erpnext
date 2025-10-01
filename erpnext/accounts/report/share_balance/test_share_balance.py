import frappe
from frappe.tests.utils import FrappeTestCase
from erpnext.accounts.report.share_balance.share_balance import execute
import frappe.utils

class TestShareBalance(FrappeTestCase):

    def setUp(self):
    
        if not frappe.db.exists("Shareholder", "_Test Shareholder"):
            self.shareholder = frappe.get_doc({
                "doctype": "Shareholder",
                "title": "_Test Shareholder",
                "shareholder_name": "_Test Shareholder",
                "share_balance": [
                    {
                        "title": "Equity",
                        "share_type": "Equity",
                        "no_of_shares": 10,
                        "rate": 100,
                        "amount": 1000,
                        "from_no": 1,
                        "to_no": 10
                    },
                    {
                        "title": "Preference",
                        "share_type": "Preference",
                        "no_of_shares": 5,
                        "rate": 200,
                        "amount": 1000,
                        "from_no": 11,
                        "to_no": 15
                    }
                ]
            }).insert(ignore_permissions=True)
        else:
            self.shareholder = frappe.get_doc("Shareholder", "_Test Shareholder")

    def tearDown(self):
       
        frappe.db.rollback()

    def test_execute_with_shareholder(self):
        filters = {"date": frappe.utils.now(), "shareholder": self.shareholder.name}
        columns, data = execute(filters)


        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)  

       
        expected_keys = [self.shareholder.name, "Equity", 10, 100, 1000]
        self.assertEqual(data[0], expected_keys)

        expected_keys2 = [self.shareholder.name, "Preference", 5, 200, 1000]
        self.assertEqual(data[1], expected_keys2)

    def test_execute_without_shareholder(self):
        filters = {"date": "2025-10-01"}  
        columns, data = execute(filters)

        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 0) 

    def test_execute_missing_date(self):
        filters = {"shareholder": "_Test Shareholder"}
        with self.assertRaises(frappe.exceptions.ValidationError):
            execute(filters)
