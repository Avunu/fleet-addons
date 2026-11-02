# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import vin as vin_tools


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    # Everything the decoder writes is prefixed, which keeps it clear on the
    # form that these came from the VIN rather than from someone's memory, and
    # keeps us out of the way of OCA fleet modules adding spec fields.
    vin_body_class = fields.Char("Body Class", readonly=True)
    vin_drive_type = fields.Char("Drive Type", readonly=True)
    vin_engine_configuration = fields.Char("Engine Configuration", readonly=True)
    vin_engine_cylinders = fields.Integer("Cylinders", readonly=True)
    vin_engine_displacement_l = fields.Float(
        "Displacement (L)", digits=(4, 1), readonly=True
    )
    vin_engine_manufacturer = fields.Char("Engine Manufacturer", readonly=True)
    vin_gvwr = fields.Char("GVWR Class", readonly=True)
    vin_manufacturer = fields.Char("Manufacturer", readonly=True)
    vin_plant_country = fields.Char("Built In", readonly=True)
    vin_series = fields.Char("Series", readonly=True)
    vin_transmission_speeds = fields.Integer("Transmission Speeds", readonly=True)
    vin_transmission_style = fields.Char("Transmission Style", readonly=True)
    vin_trim = fields.Char("Trim", readonly=True)

    vin_decoded_on = fields.Datetime("VIN Decoded On", readonly=True, copy=False)
    vin_decode_note = fields.Char("VIN Decode Note", readonly=True, copy=False)
    vin_check_digit_ok = fields.Boolean(
        "VIN Check Digit Valid",
        compute="_compute_vin_check_digit_ok",
        help="The 9th character of a VIN is a checksum of the other 16. A "
        "mismatch usually means a transcription error, though some "
        "manufacturers do not follow the standard.",
    )

    @api.depends("vin_sn")
    def _compute_vin_check_digit_ok(self):
        for vehicle in self:
            vehicle.vin_check_digit_ok = vin_tools.check_digit_matches(vehicle.vin_sn)

    def action_decode_vin(self):
        """Fill the vehicle in from its VIN.

        Runs synchronously: this sits behind a button the advisor pressed and
        is waiting on, and vPIC answers in well under a second.
        """
        decoder = self.env["shop.vin.decoder"]

        # Validate everything before spending a round trip, and refuse the
        # whole batch rather than silently skipping records.
        problems = []
        for vehicle in self:
            problem = vin_tools.describe_problem(vehicle.vin_sn)
            if problem:
                problems.append(f"{vehicle.display_name}: {problem}")
        if problems:
            raise UserError(
                _("These vehicles cannot be decoded:\n\n%s", "\n".join(problems))
            )

        decoded = decoder.decode(self.mapped("vin_sn"))

        undecoded = self.browse()
        for vehicle in self:
            record = decoded.get(vin_tools.normalise(vehicle.vin_sn))
            if not record:
                undecoded |= vehicle
                continue
            vehicle._apply_vin_decode(record)

        if undecoded:
            raise UserError(
                _(
                    "The NHTSA service returned nothing for:\n\n%s\n\n"
                    "This usually means the VIN is not a US-market vehicle.",
                    "\n".join(undecoded.mapped("vin_sn")),
                )
            )
        return True

    def _apply_vin_decode(self, record):
        """Write a decoded record onto this vehicle and log what changed.

        The chatter entry is the point: a decode overwrites fields, and the
        shop needs to be able to see afterwards what the VIN actually said
        versus what someone typed.
        """
        self.ensure_one()
        decoder = self.env["shop.vin.decoder"]
        values = decoder.values_from_record(record)

        notes = []
        model = decoder._find_model(record)
        if model:
            values["model_id"] = model.id
        else:
            described = " ".join(
                part
                for part in (
                    record.get("ModelYear"),
                    record.get("Make"),
                    record.get("Model"),
                )
                if part
            )
            if described:
                notes.append(
                    _(
                        "Decoded as %s, which is not in the vehicle catalog -- "
                        "pick or create a model by hand.",
                        described,
                    )
                )

        # ErrorCode is a comma-separated list; "0" means a clean decode. A
        # check-digit complaint still comes with usable data, so it is a note
        # rather than a failure.
        error_text = (record.get("ErrorText") or "").strip()
        codes = {code.strip() for code in (record.get("ErrorCode") or "").split(",")}
        if codes - {"0", ""} and error_text:
            notes.append(error_text)

        if values.get("horsepower"):
            values["power_unit"] = "horsepower"

        values["vin_decoded_on"] = fields.Datetime.now()
        values["vin_decode_note"] = notes[0] if notes else False

        before = {key: self[key] for key in values}
        self.write(values)
        self._post_decode_message(record, values, before, notes)

    def _post_decode_message(self, record, values, before, notes):
        self.ensure_one()
        interesting = [
            ("Model", "model_id"),
            ("Model Year", "model_year"),
            ("Trim", "vin_trim"),
            ("Engine", "vin_engine_displacement_l"),
            ("Cylinders", "vin_engine_cylinders"),
            ("Drive Type", "vin_drive_type"),
            ("Fuel Type", "fuel_type"),
            ("Transmission", "vin_transmission_style"),
        ]
        rows = Markup()
        for label, field_name in interesting:
            if field_name not in values:
                continue
            new = self[field_name]
            new = new.display_name if hasattr(new, "display_name") else new
            old = before.get(field_name)
            old = old.display_name if hasattr(old, "display_name") else old
            # Markup's % escapes its arguments, which matters because every
            # one of these values came off a third-party API.
            if old and old != new:
                rows += Markup("<li><b>%s:</b> %s <i>(was %s)</i></li>") % (
                    label,
                    new,
                    old,
                )
            else:
                rows += Markup("<li><b>%s:</b> %s</li>") % (label, new)

        body = Markup("<p>%s</p>") % _("VIN decoded from NHTSA vPIC.")
        if rows:
            body += Markup("<ul>%s</ul>") % rows
        for note in notes:
            body += Markup("<p><i>%s</i></p>") % note
        self.message_post(body=body)
