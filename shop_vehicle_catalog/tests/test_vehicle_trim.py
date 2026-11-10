# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from lxml import etree
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestVehicleTrim(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.camry = cls.env.ref("shop_vehicle_catalog.model_toyota_camry")
        cls.corolla = cls.env.ref("shop_vehicle_catalog.model_toyota_corolla")
        Trim = cls.env["fleet.vehicle.trim"]
        cls.camry_le = Trim.create({"name": "LE", "model_id": cls.camry.id})
        cls.camry_se = Trim.create({"name": "SE", "model_id": cls.camry.id})
        cls.corolla_le = Trim.create({"name": "LE", "model_id": cls.corolla.id})

    def _vehicle(self, model, trim=None, plate="TRIM-001"):
        return self.env["fleet.vehicle"].create(
            {
                "model_id": model.id,
                "trim_id": trim.id if trim else False,
                "license_plate": plate,
            }
        )

    def test_model_lists_its_trims(self):
        self.assertEqual(self.camry.trim_ids, self.camry_le | self.camry_se)
        self.assertEqual(self.corolla.trim_ids, self.corolla_le)

    def test_trim_names_are_per_model(self):
        """LE exists on both the Camry and the Corolla, but not twice on one."""
        self.assertEqual(self.camry_le.name, self.corolla_le.name)
        with (
            self.assertRaises(IntegrityError),
            mute_logger("odoo.sql_db"),
            self.env.cr.savepoint(),
        ):
            self.env["fleet.vehicle.trim"].create(
                {"name": "LE", "model_id": self.camry.id}
            )

    def test_trim_takes_manufacturer_from_model(self):
        self.assertEqual(self.camry_le.brand_id, self.camry.brand_id)

    def test_vehicle_with_matching_trim(self):
        vehicle = self._vehicle(self.camry, self.camry_se)
        self.assertEqual(vehicle.trim_id, self.camry_se)

    def test_vehicle_trim_is_optional(self):
        self.assertFalse(self._vehicle(self.camry).trim_id)

    def test_trim_of_another_model_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._vehicle(self.camry, self.corolla_le)

    def test_changing_model_under_a_trim_is_rejected(self):
        vehicle = self._vehicle(self.camry, self.camry_le)
        with self.assertRaises(ValidationError):
            vehicle.model_id = self.corolla

    def test_changing_model_in_the_form_clears_the_trim(self):
        with Form(self.env["fleet.vehicle"]) as form:
            form.model_id = self.camry
            form.trim_id = self.camry_le
            self.assertEqual(form.trim_id, self.camry_le)
            form.model_id = self.corolla
            self.assertFalse(form.trim_id)
            form.license_plate = "TRIM-002"

    def test_form_keeps_a_trim_that_still_fits(self):
        vehicle = self._vehicle(self.camry, self.camry_le, plate="TRIM-003")
        with Form(vehicle) as form:
            form.model_id = self.camry
            self.assertEqual(form.trim_id, self.camry_le)

    def test_trim_in_use_cannot_be_deleted(self):
        self._vehicle(self.camry, self.camry_le)
        with (
            self.assertRaises(IntegrityError),
            mute_logger("odoo.sql_db"),
            self.env.cr.savepoint(),
        ):
            self.camry_le.unlink()

    def test_model_form_has_trim_levels_tab(self):
        arch = etree.fromstring(
            self.env["fleet.vehicle.model"].get_view(view_type="form")["arch"]
        )
        self.assertTrue(
            arch.xpath("//page[@name='trim_levels']//field[@name='trim_ids']")
        )

    def test_vehicle_form_has_trim_under_model(self):
        arch = etree.fromstring(
            self.env["fleet.vehicle"].get_view(view_type="form")["arch"]
        )
        title = arch.xpath("//div[hasclass('oe_title')]")[0]
        names = [f.get("name") for f in title.iter("field")]
        self.assertIn("trim_id", names)
        self.assertLess(names.index("model_id"), names.index("trim_id"))

    def test_users_can_read_but_not_edit_trims(self):
        user = self.env["res.users"].create(
            {
                "name": "Fleet Advisor",
                "login": "fleet_advisor_trim",
                "groups_id": [(6, 0, [self.env.ref("fleet.fleet_group_user").id])],
            }
        )
        trim = self.camry_le.with_user(user)
        self.assertEqual(trim.name, "LE")
        with self.assertRaises(AccessError):
            trim.name = "Renamed"
