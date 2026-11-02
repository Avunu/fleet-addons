# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
{
    "name": "Shop Vehicle Catalog",
    "summary": "US vehicle make/model catalog for Fleet, with model years and a "
    "Year/Make/Model picker. Covers light-duty autos and Class 6-8 trucks.",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Fleet",
    "author": "Avunu LLC",
    "website": "https://github.com/Avunu/fleet-addons",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "fleet",
    ],
    "data": [
        # Order matters: models reference categories and brands by XML ID.
        "data/fleet.vehicle.model.category.csv",
        "data/fleet.vehicle.model.brand.csv",
        "data/fleet.vehicle.model.csv",
        "views/fleet_vehicle_model_views.xml",
        "views/fleet_vehicle_views.xml",
    ],
}
