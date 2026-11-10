# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class FleetVehicleTrim(models.Model):
    """A trim level of a vehicle model: Camry LE, Camry SE, Camry XSE...

    Trims hang off a model rather than off a brand because a trim name only
    means something next to its model ("Limited" is a different car on a
    Tahoe than on an F-150).
    """

    _name = "fleet.vehicle.trim"
    _description = "Vehicle Trim Level"
    _order = "model_id, sequence, name"

    name = fields.Char(string="Trim Level", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "fleet.vehicle.model",
        string="Model",
        required=True,
        index=True,
        ondelete="cascade",
    )
    brand_id = fields.Many2one(
        related="model_id.brand_id",
        string="Manufacturer",
        store=True,
        index=True,
    )

    _sql_constraints = [  # noqa: RUF012 - Odoo's constraint declaration
        (
            "model_name_unique",
            "unique(model_id, name)",
            "This model already has a trim level with that name.",
        ),
    ]
