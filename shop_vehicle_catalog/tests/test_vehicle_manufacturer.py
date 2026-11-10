# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from lxml import etree

from odoo.tests import Form, TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestVehicleManufacturer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.toyota = cls.env.ref("fleet.brand_toyota")
        cls.honda = cls.env.ref("fleet.brand_honda")
        cls.camry = cls.env.ref("shop_vehicle_catalog.model_toyota_camry")
        cls.corolla = cls.env.ref("shop_vehicle_catalog.model_toyota_corolla")
        cls.accord = cls.env.ref("shop_vehicle_catalog.model_honda_accord")

    def _vehicle(self, model, plate="MFR-001"):
        return self.env["fleet.vehicle"].create(
            {"model_id": model.id, "license_plate": plate}
        )

    def test_manufacturer_follows_model(self):
        self.assertEqual(self._vehicle(self.camry).brand_id, self.toyota)
        self.assertEqual(self._vehicle(self.accord, "MFR-002").brand_id, self.honda)

    def test_manufacturer_follows_a_model_change(self):
        vehicle = self._vehicle(self.camry)
        vehicle.model_id = self.accord
        self.assertEqual(vehicle.brand_id, self.honda)

    def test_manufacturer_follows_the_models_brand(self):
        """Fixing a model's brand in the catalog carries over to its vehicles,
        as it did when brand_id was a plain related field."""
        vehicle = self._vehicle(self.camry)
        model = self.env["fleet.vehicle.model"].create(
            {"name": "Moved", "brand_id": self.toyota.id}
        )
        vehicle.model_id = model
        model.brand_id = self.honda
        self.assertEqual(vehicle.brand_id, self.honda)

    def test_editing_manufacturer_never_rebrands_the_model(self):
        """The reason brand_id is computed rather than related.

        As a related field, writing it on a vehicle would write the shared
        model's brand too, silently re-branding every vehicle of that model.
        """
        vehicle = self._vehicle(self.camry)
        other = self._vehicle(self.camry, "MFR-003")
        vehicle.brand_id = self.honda
        self.assertEqual(self.camry.brand_id, self.toyota)
        self.assertEqual(other.brand_id, self.toyota)

    def test_picking_a_manufacturer_first_keeps_it(self):
        vehicle = self.env["fleet.vehicle"].new({"brand_id": self.honda.id})
        self.assertEqual(vehicle.brand_id, self.honda)
        self.assertFalse(vehicle.model_id)

    def test_form_picking_a_model_fills_the_manufacturer(self):
        with Form(self.env["fleet.vehicle"]) as form:
            form.model_id = self.camry
            self.assertEqual(form.brand_id, self.toyota)
            form.license_plate = "MFR-004"

    def test_form_changing_manufacturer_clears_a_model_of_another_make(self):
        with Form(self.env["fleet.vehicle"]) as form:
            form.model_id = self.camry
            form.brand_id = self.honda
            self.assertFalse(form.model_id)
            self.assertEqual(form.brand_id, self.honda)
            form.model_id = self.accord
            form.license_plate = "MFR-005"

    def test_form_keeps_a_model_of_the_same_make(self):
        with Form(self.env["fleet.vehicle"]) as form:
            form.model_id = self.camry
            form.brand_id = self.toyota
            self.assertEqual(form.model_id, self.camry)
            form.license_plate = "MFR-006"

    def test_existing_vehicles_keep_their_manufacturer_on_upgrade(self):
        """Related -> computed must not blank brand_id on records that exist."""
        vehicle = self._vehicle(self.corolla)
        vehicle.invalidate_recordset()
        self.assertEqual(vehicle.brand_id, self.toyota)

    def test_group_by_manufacturer_still_works(self):
        self._vehicle(self.camry)
        groups = self.env["fleet.vehicle"].read_group(
            [("license_plate", "=", "MFR-001")], ["brand_id"], ["brand_id"]
        )
        self.assertEqual(groups[0]["brand_id"][0], self.toyota.id)


@tagged("post_install", "-at_install")
class TestVehicleFormLayout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        arch = cls.env["fleet.vehicle"].get_view(view_type="form")["arch"]
        cls.form = etree.fromstring(arch)
        cls.title = cls.form.xpath("//div[hasclass('oe_title')]")[0]

    def test_title_reads_year_manufacturer_model(self):
        names = [f.get("name") for f in self.title.iter("field")]
        self.assertLess(names.index("model_year"), names.index("brand_id"))
        self.assertLess(names.index("brand_id"), names.index("model_id"))

    def test_manufacturer_cannot_be_created_from_the_vehicle(self):
        brand = self.title.xpath(".//field[@name='brand_id']")[0]
        self.assertIn("no_create", brand.get("options"))

    def _model_domain(self, **context):
        node = self.title.xpath(".//field[@name='model_id']")[0]
        return safe_eval(node.get("domain"), dict(context))

    def test_model_domain_without_selection_offers_everything(self):
        self.assertEqual(self._model_domain(brand_id=False, model_year_int=0), [])

    def test_model_domain_filters_by_manufacturer(self):
        self.assertEqual(
            self._model_domain(brand_id=7, model_year_int=0),
            [("brand_id", "=", 7)],
        )

    def test_model_domain_filters_by_year(self):
        self.assertEqual(
            self._model_domain(brand_id=False, model_year_int=2015),
            [("year_start", "<=", 2015), ("year_end", ">=", 2015)],
        )

    def test_model_domain_filters_by_both(self):
        self.assertEqual(
            self._model_domain(brand_id=7, model_year_int=2015),
            [
                ("brand_id", "=", 7),
                ("year_start", "<=", 2015),
                ("year_end", ">=", 2015),
            ],
        )

    def test_model_domain_matches_real_models(self):
        """The domain must select the right records, not just parse."""
        toyota = self.env.ref("fleet.brand_toyota")
        domain = self._model_domain(brand_id=toyota.id, model_year_int=2015)
        found = self.env["fleet.vehicle.model"].search(domain)
        self.assertTrue(found)
        self.assertEqual(found.brand_id, toyota)
        self.assertIn(self.env.ref("shop_vehicle_catalog.model_toyota_camry"), found)
