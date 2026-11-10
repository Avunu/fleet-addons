# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestYearFormat(TransactionCase):
    """Years are digits, not quantities: "2015", never "2,015"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Model = cls.env["fleet.vehicle.model"]
        cls.form = etree.fromstring(Model.get_view(view_type="form")["arch"])
        cls.list = etree.fromstring(Model.get_view(view_type="list")["arch"])

    def assertUnformatted(self, arch, name):
        nodes = arch.xpath(f"//field[@name='{name}']")
        self.assertTrue(nodes, f"{name} should be in the view")
        for node in nodes:
            # View options are JS-flavoured: lowercase true/false.
            options = safe_eval(
                node.get("options") or "{}", {"true": True, "false": False}
            )
            self.assertIs(
                options.get("enable_formatting"),
                False,
                f"{name} must not be shown with a thousands separator",
            )

    def test_model_form_years_have_no_separator(self):
        for name in ("year_start", "year_end", "model_year"):
            self.assertUnformatted(self.form, name)

    def test_model_list_years_have_no_separator(self):
        for name in ("year_start", "year_end"):
            self.assertUnformatted(self.list, name)
