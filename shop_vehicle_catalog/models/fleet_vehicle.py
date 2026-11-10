# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    # fleet.vehicle.model_year is a Char, so it cannot be compared against the
    # catalog's Integer year bounds in a view domain. This mirrors it as an int
    # purely so the Model dropdown can filter on it.
    model_year_int = fields.Integer(
        string="Model Year (numeric)",
        compute="_compute_model_year_int",
        help="Numeric form of Model Year, used to filter the model list.",
    )

    trim_id = fields.Many2one(
        "fleet.vehicle.trim",
        string="Trim Level",
        tracking=True,
        index="btree_not_null",
        ondelete="restrict",
        domain="[('model_id', '=', model_id)]",
        help="Trim level of the vehicle. Only the trims of the selected model "
        "can be chosen.",
    )

    @api.depends("model_year")
    def _compute_model_year_int(self):
        for vehicle in self:
            try:
                vehicle.model_year_int = int((vehicle.model_year or "").strip())
            except ValueError:
                vehicle.model_year_int = 0

    @api.constrains("trim_id", "model_id")
    def _check_trim_belongs_to_model(self):
        for vehicle in self.filtered("trim_id"):
            if vehicle.trim_id.model_id != vehicle.model_id:
                raise ValidationError(
                    _(
                        "The trim level %(trim)s belongs to %(trim_model)s, "
                        "not to %(model)s.",
                        trim=vehicle.trim_id.name,
                        trim_model=vehicle.trim_id.model_id.display_name,
                        model=vehicle.model_id.display_name,
                    )
                )

    @api.onchange("model_id")
    def _onchange_model_id_clear_trim(self):
        """A trim of the previous model means nothing on the new one."""
        for vehicle in self:
            if vehicle.trim_id and vehicle.trim_id.model_id != vehicle.model_id:
                vehicle.trim_id = False

    @api.onchange("model_id", "model_year")
    def _onchange_catalog_year_match(self):
        """Warn, but do not block, when the year and model disagree.

        A hard constraint would be wrong here: grey-market imports, re-titled
        vehicles and early-release model years all legitimately fall outside the
        catalog's range, and the shop still has to write the job up.
        """
        self.ensure_one()
        if not self.model_id or not self.model_year_int:
            return
        if self.model_id.covers_year(self.model_year_int):
            return
        return {
            "warning": {
                "title": _("Check the model year"),
                "message": _(
                    "%(model)s is not listed as sold in %(year)s "
                    "(catalog says %(range)s).\n\n"
                    "This is only a warning -- imports and re-titled vehicles do fall "
                    "outside the catalog. Confirm against the VIN before saving.",
                    model=self.model_id.display_name,
                    year=self.model_year_int,
                    range=self.model_id.year_set or _("no years recorded"),
                ),
            }
        }
