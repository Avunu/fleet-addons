# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetVehicleModelMerge(models.TransientModel):
    """Fold duplicate vehicle models into one.

    Every record that points at a duplicate (vehicles first) is moved to the
    model kept, trims of the same name are folded together, and the
    duplicates are then removed.
    """

    _name = "fleet.vehicle.model.merge"
    _description = "Merge Vehicle Models"

    model_ids = fields.Many2many(
        "fleet.vehicle.model",
        string="Models",
        required=True,
        context={"active_test": False},
    )
    target_id = fields.Many2one(
        "fleet.vehicle.model",
        string="Keep",
        required=True,
        domain="[('id', 'in', model_ids)]",
        context={"active_test": False},
        help="The model that stays. The others are merged into it.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") != "fleet.vehicle.model":
            return res
        records = (
            self.env["fleet.vehicle.model"]
            .with_context(active_test=False)
            .browse(self.env.context.get("active_ids") or [])
        )
        if "model_ids" in fields_list:
            res["model_ids"] = [fields.Command.set(records.ids)]
        if "target_id" in fields_list and records:
            res["target_id"] = self._default_target(records).id
        return res

    def _default_target(self, records):
        """The catalog's record if there is one, else the most used."""
        catalog = records.filtered("nhtsa_model_id") or records.filtered(
            lambda record: record.get_external_id().get(record.id)
        )
        candidates = catalog or records
        return max(
            candidates,
            key=lambda record: (record.vehicle_count, -record.id),
        )

    def action_merge(self):
        self.ensure_one()
        target = self.target_id
        duplicates = self.model_ids - target
        if not duplicates:
            raise UserError(_("Select at least two models to merge."))
        if target not in self.model_ids:
            raise UserError(_("The model kept must be one of the selected models."))
        target._merge_from(duplicates)
        return {
            "type": "ir.actions.act_window",
            "res_model": "fleet.vehicle.model",
            "res_id": target.id,
            "views": [[False, "form"]],
            "target": "current",
        }
