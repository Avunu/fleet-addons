# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import _, fields, models

# The catalog's own data files: a record loaded from them comes back on the
# next module update if it is deleted, so a merged-away catalog model is
# archived instead.
CATALOG_MODULE = "shop_vehicle_catalog"


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
        help="Every year this model was sold in, as compressed ranges, "
        'e.g. "1985-2001,2023-2027".',
    )
    trim_ids = fields.One2many(
        "fleet.vehicle.trim",
        "model_id",
        string="Trim Levels",
        help="The trim levels this model is sold in, e.g. LE, SE and XSE.",
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
