# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestModelMerge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["fleet.vehicle.model"]
        cls.Vehicle = cls.env["fleet.vehicle"]
        cls.Trim = cls.env["fleet.vehicle.trim"]
        cls.prius = cls.env.ref("shop_vehicle_catalog.model_toyota_prius")
        cls.toyota = cls.prius.brand_id

    def _handmade(self, name="Prius", **vals):
        return self.Model.create({"name": name, "brand_id": self.toyota.id, **vals})

    def _merge(self, models, target):
        wizard = Form(
            self.env["fleet.vehicle.model.merge"].with_context(
                active_model="fleet.vehicle.model", active_ids=models.ids
            )
        )
        wizard.target_id = target
        return wizard.save().action_merge()

    # -- merge -------------------------------------------------------------

    def test_default_keeps_the_catalog_model(self):
        dup = self._handmade()
        wizard = (
            self.env["fleet.vehicle.model.merge"]
            .with_context(
                active_model="fleet.vehicle.model", active_ids=[dup.id, self.prius.id]
            )
            .new({})
        )
        defaults = wizard.default_get(["model_ids", "target_id"])
        self.assertEqual(defaults["target_id"], self.prius.id)

    def test_merge_moves_vehicles_and_removes_duplicates(self):
        dup = self._handmade()
        dup2 = self._handmade("prius")
        vehicle = self.Vehicle.create({"model_id": dup.id, "model_year": "2015"})
        vehicle2 = self.Vehicle.create({"model_id": dup2.id})
        self._merge(dup + dup2 + self.prius, self.prius)
        self.assertEqual(vehicle.model_id, self.prius)
        self.assertEqual(vehicle2.model_id, self.prius)
        self.assertFalse(dup.exists())
        self.assertFalse(dup2.exists())
        self.assertIn("Merged in", self.prius.message_ids[0].body)

    def test_merge_folds_trims(self):
        dup = self._handmade()
        kept_le = self.Trim.create({"name": "LE", "model_id": self.prius.id})
        dup_le = self.Trim.create({"name": "le", "model_id": dup.id})
        dup_xle = self.Trim.create({"name": "XLE", "model_id": dup.id})
        on_le = self.Vehicle.create({"model_id": dup.id, "trim_id": dup_le.id})
        on_xle = self.Vehicle.create({"model_id": dup.id, "trim_id": dup_xle.id})
        self._merge(dup + self.prius, self.prius)
        self.assertEqual(on_le.trim_id, kept_le)
        self.assertEqual(on_le.model_id, self.prius)
        self.assertFalse(dup_le.exists())
        self.assertEqual(dup_xle.model_id, self.prius)
        self.assertEqual(on_xle.trim_id, dup_xle)

    def test_merge_fills_missing_years(self):
        kept = self._handmade("Kept")
        dup = self._handmade(
            "Dup", year_start=2001, year_end=2009, year_set="2001-2009"
        )
        self._merge(kept + dup, kept)
        self.assertEqual((kept.year_start, kept.year_end), (2001, 2009))
        self.assertEqual(kept.year_set, "2001-2009")

    def test_merge_keeps_target_years(self):
        dup = self._handmade(year_start=1950, year_end=1951)
        start, end = self.prius.year_start, self.prius.year_end
        self._merge(dup + self.prius, self.prius)
        self.assertEqual((self.prius.year_start, self.prius.year_end), (start, end))

    def test_merging_away_a_catalog_model_archives_it(self):
        """Deleted catalog records would come back on the next module update."""
        kept = self._handmade()
        self._merge(kept + self.prius, kept)
        self.assertTrue(self.prius.exists())
        self.assertFalse(self.prius.active)

    def test_merge_needs_two_models(self):
        wizard = self.env["fleet.vehicle.model.merge"].create(
            {"model_ids": [(6, 0, self.prius.ids)], "target_id": self.prius.id}
        )
        with self.assertRaises(UserError):
            wizard.action_merge()
