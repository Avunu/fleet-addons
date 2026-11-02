# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


def parse_year_set(year_set):
    """Expand a compressed year set such as "1987-1999,2001-2003" to a set of ints.

    This is the format open-vehicle-db stores in models.csv, which keeps a model
    on one line no matter how many years it covers. Returns an empty set for
    anything unparseable so a malformed value degrades to "no opinion" rather
    than breaking a picker.
    """
    years = set()
    for chunk in (year_set or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        start, _, end = chunk.partition("-")
        try:
            first = int(start)
            last = int(end) if end else first
        except ValueError:
            continue
        if last < first:
            continue
        years.update(range(first, last + 1))
    return years


class FleetVehicleModel(models.Model):
    _inherit = "fleet.vehicle.model"

    # year_start/year_end bound the picker domain and are indexed for it.
    # year_set carries the exact years, including gaps that a start/end range
    # cannot express -- the Acura Integra ran 1985-2001 and again 2023-2027.
    year_start = fields.Integer(
        string="First Year",
        index=True,
        help="First model year this vehicle was sold in.",
    )
    year_end = fields.Integer(
        string="Last Year",
        index=True,
        help="Last model year this vehicle was sold in.",
    )
    year_set = fields.Char(
        string="Model Years",
        help='Every year this model was sold in, as compressed ranges, e.g. "1985-2001,2023-2027".',
    )
    nhtsa_model_id = fields.Integer(
        string="NHTSA Model ID",
        index=True,
        help="Identifier of this model in the NHTSA vPIC database. Empty for "
        "models that were not imported from the vehicle catalog.",
    )

    def covers_year(self, year):
        """True if this model was sold in `year`.

        Models with no catalog year data answer True: an unknown range must not
        make a hand-created model unpickable.
        """
        self.ensure_one()
        try:
            year = int(year)
        except (TypeError, ValueError):
            return True
        years = parse_year_set(self.year_set)
        if years:
            return year in years
        if self.year_start and self.year_end:
            return self.year_start <= year <= self.year_end
        return True
