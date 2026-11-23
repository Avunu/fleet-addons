# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# The catalog's own data files: a record loaded from them comes back on the
# next module update if it is deleted, so a merged-away catalog model is
# archived instead.
CATALOG_MODULE = "shop_vehicle_catalog"


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


class FleetVehicleModel(models.Model):
    _inherit = "fleet.vehicle.model"

    def _merge_from(self, duplicates):
        """Move everything that points at ``duplicates`` onto this model."""
        self.ensure_one()
        target = self.sudo()
        duplicates = duplicates.sudo().with_context(active_test=False)
        target._merge_trims(duplicates)
        target._merge_references(duplicates)
        target._merge_details(duplicates)
        target._merge_chatter(duplicates)
        target.message_post(
            body=_(
                "Merged in: %(models)s",
                models=", ".join(duplicates.mapped("display_name")),
            )
        )
        catalog = duplicates.filtered(
            lambda record: any(
                xmlid.startswith(f"{CATALOG_MODULE}.")
                for xmlid in record._get_external_ids().get(record.id, [])
            )
        )
        catalog.active = False
        (duplicates - catalog).unlink()

    def _merge_trims(self, duplicates):
        """A trim name is unique per model: fold a duplicate's trim into the
        kept model's trim of that name, and move the others across.

        Done before the vehicles move, so a vehicle's trim and model change
        together and never disagree.
        """
        Vehicle = self.env["fleet.vehicle"].sudo().with_context(active_test=False)
        Trim = self.env["fleet.vehicle.trim"].sudo().with_context(active_test=False)
        kept = {
            trim.name.strip().lower(): trim
            for trim in Trim.search([("model_id", "=", self.id)])
        }
        for trim in Trim.search([("model_id", "in", duplicates.ids)]):
            same = kept.get(trim.name.strip().lower())
            if same:
                Vehicle.search([("trim_id", "=", trim.id)]).write(
                    {"model_id": self.id, "trim_id": same.id}
                )
                trim.unlink()
            else:
                trim.model_id = self
                kept[trim.name.strip().lower()] = trim

    def _merge_references(self, duplicates):
        """Repoint every stored many2one and many2many to this model."""
        for model_name, field in self._merge_reference_fields():
            Model = self.env[model_name].sudo().with_context(active_test=False)
            records = Model.search([(field.name, "in", duplicates.ids)])
            if not records:
                continue
            if field.type == "many2one":
                records.write({field.name: self.id})
            else:
                records.write(
                    {
                        field.name: [fields.Command.unlink(d.id) for d in duplicates]
                        + [fields.Command.link(self.id)]
                    }
                )

    def _merge_reference_fields(self):
        for model_name, Model in self.env.registry.items():
            if Model._abstract or Model._transient or not Model._auto:
                continue
            for field in Model._fields.values():
                if (
                    field.type in ("many2one", "many2many")
                    and field.comodel_name == self._name
                    and field.store
                    and not field.compute
                    and not field.related
                ):
                    yield model_name, field

    def _merge_details(self, duplicates):
        """Fill what the kept model lacks from the duplicates: years, vendors,
        category. What the kept model already has stays."""
        vals = {}
        for name in ("year_start", "year_end", "year_set", "category_id"):
            if not self[name]:
                donor = duplicates.filtered(name)[:1]
                if donor:
                    vals[name] = (
                        donor[name].id if name == "category_id" else donor[name]
                    )
        vendors = duplicates.vendors - self.vendors
        if vendors:
            vals["vendors"] = [fields.Command.link(v.id) for v in vendors]
        if vals:
            self.write(vals)

    def _merge_chatter(self, duplicates):
        """Keep the duplicates' notes and files on the kept model."""
        domain = [("model", "=", self._name), ("res_id", "in", duplicates.ids)]
        self.env["mail.message"].sudo().search(domain).write({"res_id": self.id})
        self.env["ir.attachment"].sudo().search(
            [("res_model", "=", self._name), ("res_id", "in", duplicates.ids)]
        ).write({"res_id": self.id})
