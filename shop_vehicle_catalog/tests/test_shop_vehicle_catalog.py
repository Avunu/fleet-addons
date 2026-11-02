# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.tests import Form, TransactionCase, tagged

from ..models.fleet_vehicle_model import parse_year_set


@tagged("post_install", "-at_install")
class TestShopVehicleCatalog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["fleet.vehicle.model"]
        cls.Brand = cls.env["fleet.vehicle.model.brand"]

    def test_no_duplicate_brands(self):
        """The catalog must reuse core Odoo's brands, not shadow them.

        There is no SQL uniqueness constraint on brand name, so a missed alias
        in the generator would silently produce two "Alfa" brands with the
        models split between them.
        """
        names = [
            b.name.strip().lower()
            for b in self.Brand.with_context(active_test=False).search([])
        ]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertFalse(
            duplicates, f"Duplicate brand names after install: {duplicates}"
        )

    def test_reuses_core_brands(self):
        """Makes that core Odoo already ships keep the core record and its logo."""
        for xml_id, make in [
            ("fleet.brand_toyota", "Toyota"),
            ("fleet.brand_alfa", "Alfa"),
            ("fleet.brand_mercedes", "Mercedes"),
            ("fleet.brand_volkswagen", "Volkswagen"),
        ]:
            brand = self.env.ref(xml_id)
            self.assertEqual(brand.name, make)
            self.assertTrue(
                brand.model_ids,
                f"{make} should have catalog models attached to the core brand",
            )

    def test_volkswagen_is_present(self):
        """Regression on the upstream WHITE_LIST typo that dropped VW entirely."""
        golf = self.env.ref("shop_vehicle_catalog.model_volkswagen_golf")
        self.assertEqual(golf.brand_id, self.env.ref("fleet.brand_volkswagen"))
        self.assertTrue(golf.covers_year(2015))

    def test_commercial_truck_makes(self):
        """Class 6-8 makes the upstream dataset used to blacklist."""
        t680 = self.env.ref("shop_vehicle_catalog.model_kenworth_t680")
        self.assertEqual(t680.brand_id.name, "Kenworth")
        self.assertEqual(
            t680.category_id, self.env.ref("shop_vehicle_catalog.category_truck")
        )

        # Volvo Truck must be its own brand -- an XC90 and a VNL are not the
        # same manufacturer as far as the shop is concerned.
        vnl = self.env.ref("shop_vehicle_catalog.model_volvo_truck_vnl")
        self.assertNotEqual(vnl.brand_id, self.env.ref("fleet.brand_volvo"))

    def test_vehicle_type_untouched(self):
        """Every catalog model stays vehicle_type='car'.

        Core fleet views hide the odometer, transmission, seats and doors
        behind invisible="vehicle_type != 'car'". Any other value would make
        the odometer field disappear, which the repair workflow depends on.
        """
        others = self.Model.search(
            [("nhtsa_model_id", "!=", 0), ("vehicle_type", "!=", "car")]
        )
        self.assertFalse(
            others,
            f"Catalog models must stay vehicle_type='car': {others.mapped('name')}",
        )

    def test_year_bounds_and_categories(self):
        prius = self.env.ref("shop_vehicle_catalog.model_toyota_prius")
        self.assertEqual(prius.brand_id, self.env.ref("fleet.brand_toyota"))
        self.assertEqual(
            prius.category_id, self.env.ref("shop_vehicle_catalog.category_car")
        )
        self.assertEqual(prius.year_start, 2001)
        self.assertGreaterEqual(prius.year_end, 2027)

    def test_parse_year_set(self):
        self.assertEqual(parse_year_set("2020"), {2020})
        self.assertEqual(parse_year_set("2020-2022"), {2020, 2021, 2022})
        self.assertEqual(parse_year_set("1998-1999,2002"), {1998, 1999, 2002})
        # Degrades to "no opinion" rather than raising.
        self.assertEqual(parse_year_set(""), set())
        self.assertEqual(parse_year_set(None), set())
        self.assertEqual(parse_year_set("garbage"), set())
        self.assertEqual(parse_year_set("2005-2001"), set())

    def test_covers_year_handles_gaps(self):
        """The Integra ran 1985-2001, stopped, and came back in 2023."""
        integra = self.env.ref("shop_vehicle_catalog.model_acura_integra")
        self.assertIn(",", integra.year_set, "Integra should have a gapped year set")
        self.assertTrue(integra.covers_year(1995))
        self.assertTrue(integra.covers_year(2024))
        self.assertFalse(integra.covers_year(2010))
        # A year_start/year_end range alone would wrongly accept 2010.
        self.assertTrue(integra.year_start <= 2010 <= integra.year_end)

    def test_covers_year_without_catalog_data(self):
        """A hand-created model must never become unpickable."""
        brand = self.Brand.create({"name": "Catalogless Motors"})
        model = self.Model.create({"name": "Handmade", "brand_id": brand.id})
        self.assertTrue(model.covers_year(2015))
        self.assertTrue(model.covers_year(None))
        self.assertTrue(model.covers_year("not a year"))

    def test_vehicle_from_catalog_model(self):
        prius = self.env.ref("shop_vehicle_catalog.model_toyota_prius")
        vehicle = self.env["fleet.vehicle"].create(
            {"model_id": prius.id, "license_plate": "CAT-001", "model_year": "2015"}
        )
        self.assertEqual(vehicle.brand_id, self.env.ref("fleet.brand_toyota"))
        self.assertEqual(vehicle.vehicle_type, "car")
        self.assertEqual(vehicle.model_year_int, 2015)
        # Catalog models leave model_year at 0, so picking a model must not
        # clobber the year the advisor typed.
        self.assertEqual(prius.model_year, 0)
        self.assertEqual(vehicle.model_year, "2015")

    def test_model_year_int_ignores_junk(self):
        prius = self.env.ref("shop_vehicle_catalog.model_toyota_prius")
        vehicle = self.env["fleet.vehicle"].create(
            {"model_id": prius.id, "license_plate": "CAT-002", "model_year": "unknown"}
        )
        self.assertEqual(vehicle.model_year_int, 0)

    def test_year_mismatch_warns_but_does_not_block(self):
        integra = self.env.ref("shop_vehicle_catalog.model_acura_integra")
        form = Form(self.env["fleet.vehicle"])
        form.model_id = integra
        form.model_year = "2010"
        # The onchange warns; saving must still succeed, because imports and
        # re-titled vehicles legitimately fall outside the catalog.
        vehicle = form.save()
        self.assertEqual(vehicle.model_year, "2010")

        warning = vehicle._onchange_catalog_year_match()
        self.assertTrue(warning and "warning" in warning)
        vehicle.model_year = "1995"
        self.assertFalse(vehicle._onchange_catalog_year_match())
