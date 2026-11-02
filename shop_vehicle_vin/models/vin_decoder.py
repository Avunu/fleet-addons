# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import logging

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

from . import vin as vin_tools

_logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles"
DEFAULT_TIMEOUT = 20
# NHTSA caps a batch request at 50 VINs.
BATCH_SIZE = 50

# NHTSA returns "Not Applicable" and friends in fields that do not apply to the
# vehicle rather than leaving them blank. Treat those as absent.
_EMPTY_VALUES = frozenset({"", "not applicable", "n/a", "na", "none", "unknown"})

# fleet.vehicle.fuel_type is a Selection; NHTSA reports free-ish text. Matched
# on a lowercase substring, most specific first.
_FUEL_TYPE_MATCHES = (
    ("diesel", "diesel"),
    ("compressed natural gas", "cng"),
    ("natural gas", "cng"),
    ("propane", "lpg"),
    ("liquefied petroleum", "lpg"),
    ("hydrogen", "hydrogen"),
    ("fuel cell", "hydrogen"),
    ("electric", "electric"),
    ("gasoline", "gasoline"),
    ("ethanol", "gasoline"),
    ("flexible fuel", "gasoline"),
)


def _clean(value):
    """NHTSA's way of saying "no value" is inconsistent; normalise it to None."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _EMPTY_VALUES else text


def _to_int(value):
    text = _clean(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value):
    text = _clean(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class ShopVinDecoder(models.AbstractModel):
    """Client for the NHTSA vPIC VIN decoder.

    Split out from fleet.vehicle so the network call has one place to live and
    one place to be mocked. vPIC is a free US government service and needs no
    credentials, so the only configuration is the endpoint and a timeout.
    """

    _name = "shop.vin.decoder"
    _description = "NHTSA VIN Decoder"

    @api.model
    def _config(self, key, default):
        value = (
            self.env["ir.config_parameter"].sudo().get_param(f"shop_vehicle_vin.{key}")
        )
        return value or default

    @api.model
    def _request(self, path, payload=None):
        """GET or POST against vPIC and return the parsed Results list.

        Every failure mode here is an outage or a typo'd endpoint rather than
        something the user can fix in the form, so they all surface as one
        UserError telling them to try again or fall back to manual entry.
        """
        base_url = self._config("base_url", DEFAULT_BASE_URL).rstrip("/")
        timeout = int(self._config("timeout", DEFAULT_TIMEOUT))
        url = f"{base_url}/{path}"
        try:
            if payload is None:
                response = requests.get(url, params={"format": "json"}, timeout=timeout)
            else:
                response = requests.post(
                    url, data={"format": "json", **payload}, timeout=timeout
                )
            response.raise_for_status()
            body = response.json()
        except requests.exceptions.Timeout as error:
            raise UserError(
                _(
                    "The NHTSA VIN service did not respond within %s seconds. "
                    "Try again, or fill the vehicle in by hand.",
                    timeout,
                )
            ) from error
        except requests.exceptions.RequestException as error:
            _logger.warning("VIN decode request to %s failed: %s", url, error)
            raise UserError(
                _(
                    "Could not reach the NHTSA VIN service. "
                    "Check the internet connection, or fill the vehicle in by hand."
                )
            ) from error
        except ValueError as error:
            raise UserError(
                _("The NHTSA VIN service returned a response that could not be read.")
            ) from error

        results = body.get("Results")
        if not isinstance(results, list):
            raise UserError(
                _("The NHTSA VIN service returned no results for this request.")
            )
        return results

    @api.model
    def decode(self, vins):
        """Decode VINs and return {vin: raw NHTSA record}.

        Batched because a shop backfilling its existing customer vehicles would
        otherwise make one round trip per vehicle.
        """
        wanted = [vin_tools.normalise(vin) for vin in vins]
        wanted = [vin for vin in wanted if vin]
        if not wanted:
            return {}

        decoded = {}
        for start in range(0, len(wanted), BATCH_SIZE):
            chunk = wanted[start : start + BATCH_SIZE]
            if len(chunk) == 1:
                results = self._request(f"DecodeVinValues/{chunk[0]}")
            else:
                results = self._request(
                    "DecodeVINValuesBatch/", {"data": ";".join(chunk)}
                )
            for record in results:
                returned_vin = vin_tools.normalise(record.get("VIN"))
                if returned_vin:
                    decoded[returned_vin] = record
        return decoded

    @api.model
    def _find_model(self, record):
        """Resolve a decoded record to a fleet.vehicle.model.

        Three attempts, most reliable first. Never creates a model: the catalog
        is module-managed data, and a record invented here would sit alongside
        it with no provenance. When nothing matches, the caller reports what
        was decoded and lets the advisor pick or create one.
        """
        Model = self.env["fleet.vehicle.model"]

        nhtsa_model_id = _to_int(record.get("ModelID"))
        if nhtsa_model_id:
            match = Model.search([("nhtsa_model_id", "=", nhtsa_model_id)], limit=1)
            if match:
                return match

        brand = self._find_brand(record)
        model_name = _clean(record.get("Model"))
        if brand and model_name:
            match = Model.search(
                [("brand_id", "=", brand.id), ("name", "=ilike", model_name)], limit=1
            )
            if match:
                return match
            # NHTSA writes "F-150" where a catalog might hold "F150".
            squashed = model_name.replace("-", "").replace(" ", "")
            for candidate in Model.search([("brand_id", "=", brand.id)]):
                if (
                    candidate.name.replace("-", "").replace(" ", "").upper()
                    == squashed.upper()
                ):
                    return candidate
        return Model.browse()

    @api.model
    def _find_brand(self, record):
        Brand = self.env["fleet.vehicle.model.brand"]
        nhtsa_make_id = _to_int(record.get("MakeID"))
        if nhtsa_make_id:
            match = Brand.search([("nhtsa_make_id", "=", nhtsa_make_id)], limit=1)
            if match:
                return match
        make_name = _clean(record.get("Make"))
        if make_name:
            match = Brand.search([("name", "=ilike", make_name)], limit=1)
            if match:
                return match
        return Brand.browse()

    @api.model
    def _map_fuel_type(self, record):
        """NHTSA splits fuel and electrification across two fields.

        A Prius reports FuelTypePrimary "Gasoline" and ElectrificationLevel
        "Strong HEV", and only the pair of them says "full_hybrid".
        """
        electrification = (_clean(record.get("ElectrificationLevel")) or "").lower()
        primary = (_clean(record.get("FuelTypePrimary")) or "").lower()

        if "phev" in electrification or "plug-in" in electrification:
            return (
                "plug_in_hybrid_diesel"
                if "diesel" in primary
                else "plug_in_hybrid_gasoline"
            )
        if "bev" in electrification or "battery electric" in electrification:
            return "electric"
        if "hev" in electrification or "hybrid" in electrification:
            return "full_hybrid"

        for needle, value in _FUEL_TYPE_MATCHES:
            if needle in primary:
                return value
        return None

    @api.model
    def _map_transmission(self, record):
        """Core fleet only knows manual vs automatic.

        The full style string is kept separately, so calling a DCT "automatic"
        loses nothing -- it is what the driver experiences, and vin_transmission_style
        still says exactly what it is.
        """
        style = (_clean(record.get("TransmissionStyle")) or "").lower()
        if not style:
            return None
        if "manual" in style and "automated" not in style and "automatic" not in style:
            return "manual"
        return "automatic"

    @api.model
    def values_from_record(self, record):
        """Translate a raw NHTSA record into fleet.vehicle field values.

        Only keys with a value are returned, so a sparse decode never blanks
        out something the shop already knew.
        """
        values = {
            "vin_body_class": _clean(record.get("BodyClass")),
            "vin_drive_type": _clean(record.get("DriveType")),
            "vin_engine_configuration": _clean(record.get("EngineConfiguration")),
            "vin_engine_cylinders": _to_int(record.get("EngineCylinders")),
            "vin_engine_displacement_l": _to_float(record.get("DisplacementL")),
            "vin_engine_manufacturer": _clean(record.get("EngineManufacturer")),
            "vin_gvwr": _clean(record.get("GVWR")),
            "vin_manufacturer": _clean(record.get("Manufacturer")),
            "vin_plant_country": _clean(record.get("PlantCountry")),
            "vin_series": _clean(record.get("Series")),
            "vin_transmission_speeds": _to_int(record.get("TransmissionSpeeds")),
            "vin_transmission_style": _clean(record.get("TransmissionStyle")),
            "vin_trim": _clean(record.get("Trim")),
            "doors": _to_int(record.get("Doors")),
            "horsepower": _to_int(record.get("EngineHP")),
            "model_year": _clean(record.get("ModelYear")),
            "fuel_type": self._map_fuel_type(record),
            "transmission": self._map_transmission(record),
        }
        return {key: value for key, value in values.items() if value not in (None, "")}
