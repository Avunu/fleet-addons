# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class FleetVehicleModelBrand(models.Model):
    _inherit = "fleet.vehicle.model.brand"

    # NHTSA vPIC Make_ID. Kept so a VIN decode can resolve straight to a brand
    # without matching on name, and so the catalog generator can tell an
    # imported brand from one a user typed by hand.
    nhtsa_make_id = fields.Integer(
        string="NHTSA Make ID",
        index=True,
        help="Identifier of this make in the NHTSA vPIC database. Empty for "
        "brands that were not imported from the vehicle catalog.",
    )
