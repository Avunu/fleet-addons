# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Shop Vehicle VIN Decode",
    "summary": "Decode a VIN against the NHTSA vPIC API to fill in the vehicle's "
    "model, year, engine and drivetrain.",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Fleet",
    "author": "Avunu LLC",
    "website": "https://github.com/Avunu/fleet-addons",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        # The catalog carries nhtsa_make_id / nhtsa_model_id, which is what
        # lets a decoded VIN resolve to a model without matching on name.
        "shop_vehicle_catalog",
    ],
    "data": [
        "data/ir_config_parameter.xml",
        "views/fleet_vehicle_views.xml",
    ],
}
