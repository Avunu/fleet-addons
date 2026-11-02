# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Tests for VIN decoding.

Nothing here touches the network: `_request` is patched out and fed captured
NHTSA responses. The fixtures below are trimmed from real vPIC replies, and
the VINs are real enough to exercise the check-digit rules (the F-150 one
genuinely fails its checksum, which is why NHTSA returns ErrorCode 1 for it).
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import vin as vin_tools

ACCORD_VIN = "1HGCM82633A004352"
MODEL3_VIN = "5YJ3E1EA8JF000000"
F150_VIN = "1FTFW1ET5DFC10312"

ACCORD = {
    "VIN": ACCORD_VIN,
    "Make": "HONDA",
    "MakeID": "474",
    "Model": "Accord",
    "ModelID": "1861",
    "ModelYear": "2003",
    "Trim": "EX-V6",
    "BodyClass": "Coupe",
    "VehicleType": "PASSENGER CAR",
    "EngineCylinders": "6",
    "DisplacementL": "2.998832712",
    "EngineHP": "240",
    "EngineConfiguration": "V-Shaped",
    "FuelTypePrimary": "Gasoline",
    "TransmissionStyle": "Automatic",
    "TransmissionSpeeds": "5",
    "Doors": "2",
    "GVWR": "Class 1C: 4,001 - 5,000 lb (1,814 - 2,268 kg)",
    "Manufacturer": "HONDA OF AMERICA MFG., INC.",
    "PlantCountry": "UNITED STATES (USA)",
    "ErrorCode": "0",
    "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) is correct",
    "BusType": "Not Applicable",
    "TrailerType": "Not Applicable",
}

MODEL3 = {
    "VIN": MODEL3_VIN,
    "Make": "TESLA",
    "MakeID": "441",
    "Model": "Model 3",
    "ModelID": "17834",
    "ModelYear": "2018",
    "BodyClass": "Sedan/Saloon",
    "FuelTypePrimary": "Electric",
    "ElectrificationLevel": "BEV (Battery Electric Vehicle)",
    "TransmissionStyle": "Automatic",
    "TransmissionSpeeds": "1",
    "Doors": "4",
    "ErrorCode": "0",
    "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) is correct",
}

F150 = {
    "VIN": F150_VIN,
    "Make": "FORD",
    "MakeID": "460",
    "Model": "F-150",
    "ModelID": "1801",
    "ModelYear": "2013",
    "BodyClass": "Pickup",
    "DriveType": "4WD/4-Wheel Drive/4x4",
    "EngineCylinders": "6",
    "DisplacementL": "3.5",
    "EngineHP": "365",
    "FuelTypePrimary": "Gasoline",
    "ErrorCode": "1",
    "ErrorText": "1 - Check Digit (9th position) does not calculate properly",
}


@tagged("post_install", "-at_install")
class TestVinHelpers(TransactionCase):
    """Pure VIN rules -- no Odoo state involved."""

    def test_check_digit_matches_nhtsa_verdict(self):
        self.assertTrue(vin_tools.check_digit_matches(ACCORD_VIN))
        self.assertTrue(vin_tools.check_digit_matches(MODEL3_VIN))
        # NHTSA returns ErrorCode 1 for this one for exactly this reason.
        self.assertFalse(vin_tools.check_digit_matches(F150_VIN))

    def test_normalise(self):
        self.assertEqual(vin_tools.normalise(" 1hgcm82633a004352 "), ACCORD_VIN)
        self.assertEqual(vin_tools.normalise("1HGCM826-33A004352"), ACCORD_VIN)
        self.assertEqual(vin_tools.normalise(None), "")

    def test_describe_problem(self):
        self.assertIsNone(vin_tools.describe_problem(ACCORD_VIN))
        self.assertIn("No VIN", vin_tools.describe_problem(""))
        self.assertIn("17 characters", vin_tools.describe_problem("1HGCM8263"))
        # I/O/Q get their own message because they are nearly always a misread.
        self.assertIn("never contain", vin_tools.describe_problem("1HGCM82633A00435I"))
        self.assertIn("never contain", vin_tools.describe_problem("1HGCM82633A00435O"))

    def test_check_digit_needs_valid_shape(self):
        self.assertFalse(vin_tools.check_digit_matches("TOO-SHORT"))
        self.assertFalse(vin_tools.check_digit_matches(""))


@tagged("post_install", "-at_install")
class TestVinDecoder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.decoder = cls.env["shop.vin.decoder"]
        cls.Vehicle = cls.env["fleet.vehicle"]

    def _mock_request(self, records):
        """Patch out the HTTP layer, returning `records` as the vPIC payload."""
        return patch.object(type(self.decoder), "_request", return_value=list(records))

    # -- mapping -----------------------------------------------------------

    def test_values_from_record(self):
        values = self.decoder.values_from_record(ACCORD)
        self.assertEqual(values["model_year"], "2003")
        self.assertEqual(values["vin_trim"], "EX-V6")
        self.assertEqual(values["vin_engine_cylinders"], 6)
        self.assertAlmostEqual(values["vin_engine_displacement_l"], 2.998832712)
        self.assertEqual(values["horsepower"], 240)
        self.assertEqual(values["doors"], 2)
        self.assertEqual(values["fuel_type"], "gasoline")
        self.assertEqual(values["transmission"], "automatic")

    def test_not_applicable_is_dropped(self):
        """NHTSA fills inapplicable fields with "Not Applicable", not blanks."""
        values = self.decoder.values_from_record(ACCORD)
        self.assertNotIn("vin_series", values)
        self.assertNotIn("vin_drive_type", values)

    def test_sparse_record_yields_no_keys(self):
        """A near-empty decode must not blank out what the shop already knew."""
        values = self.decoder.values_from_record({"VIN": ACCORD_VIN})
        self.assertEqual(values, {})

    def test_fuel_type_mapping(self):
        cases = [
            ({"FuelTypePrimary": "Gasoline"}, "gasoline"),
            ({"FuelTypePrimary": "Diesel"}, "diesel"),
            ({"FuelTypePrimary": "Electric"}, "electric"),
            ({"FuelTypePrimary": "Compressed Natural Gas (CNG)"}, "cng"),
            ({"FuelTypePrimary": "Liquefied Petroleum Gas (propane or LPG)"}, "lpg"),
            ({"FuelTypePrimary": "Fuel Cell"}, "hydrogen"),
            ({"FuelTypePrimary": "Flexible Fuel Vehicle (FFV)"}, "gasoline"),
            # Electrification level is what distinguishes a hybrid; a Prius
            # reports FuelTypePrimary "Gasoline" like any other car.
            (
                {
                    "FuelTypePrimary": "Gasoline",
                    "ElectrificationLevel": "Strong HEV (Hybrid Electric Vehicle)",
                },
                "full_hybrid",
            ),
            (
                {
                    "FuelTypePrimary": "Gasoline",
                    "ElectrificationLevel": "PHEV (Plug-in Hybrid Electric Vehicle)",
                },
                "plug_in_hybrid_gasoline",
            ),
            (
                {
                    "FuelTypePrimary": "Diesel",
                    "ElectrificationLevel": "PHEV (Plug-in Hybrid Electric Vehicle)",
                },
                "plug_in_hybrid_diesel",
            ),
            (
                {"FuelTypePrimary": "Electric", "ElectrificationLevel": "BEV"},
                "electric",
            ),
            ({}, None),
        ]
        for record, expected in cases:
            self.assertEqual(
                self.decoder._map_fuel_type(record), expected, f"for {record}"
            )

    def test_transmission_mapping(self):
        cases = [
            ("Manual/Standard", "manual"),
            ("Automatic", "automatic"),
            ("Continuously Variable Transmission (CVT)", "automatic"),
            # An automated manual is driven as an automatic.
            ("Automated Manual Transmission (AMT)", "automatic"),
            ("Dual-Clutch Transmission (DCT)", "automatic"),
            ("", None),
        ]
        for style, expected in cases:
            self.assertEqual(
                self.decoder._map_transmission({"TransmissionStyle": style}),
                expected,
                f"for {style!r}",
            )

    # -- catalog matching --------------------------------------------------

    def test_find_model_by_nhtsa_id(self):
        model = self.decoder._find_model(ACCORD)
        self.assertTrue(model)
        self.assertEqual(model.nhtsa_model_id, 1861)
        self.assertEqual(model.brand_id.name, "Honda")

    def test_find_model_by_name_when_id_missing(self):
        record = dict(ACCORD, ModelID="")
        model = self.decoder._find_model(record)
        self.assertEqual(model.name, "Accord")

    def test_find_model_ignores_punctuation(self):
        """NHTSA writes "F-150"; a catalog might hold "F150"."""
        record = dict(F150, ModelID="", Model="F150")
        model = self.decoder._find_model(record)
        self.assertEqual(model.nhtsa_model_id, 1801)

    def test_find_model_returns_empty_when_unknown(self):
        record = {"Make": "NOTAMAKE", "Model": "Notamodel"}
        self.assertFalse(self.decoder._find_model(record))

    def test_never_creates_catalog_records(self):
        """The catalog is module-managed; decoding must not add to it."""
        Model = self.env["fleet.vehicle.model"]
        before = Model.search_count([])
        self.decoder._find_model({"Make": "NOTAMAKE", "Model": "Notamodel"})
        self.assertEqual(Model.search_count([]), before)

    # -- end to end --------------------------------------------------------

    def test_decode_fills_vehicle(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-001",
                "vin_sn": ACCORD_VIN,
            }
        )
        with self._mock_request([ACCORD]):
            vehicle.action_decode_vin()

        self.assertEqual(vehicle.model_id.name, "Accord")
        self.assertEqual(vehicle.brand_id.name, "Honda")
        self.assertEqual(vehicle.model_year, "2003")
        self.assertEqual(vehicle.vin_trim, "EX-V6")
        self.assertEqual(vehicle.vin_engine_cylinders, 6)
        self.assertEqual(vehicle.horsepower, 240)
        self.assertEqual(vehicle.power_unit, "horsepower")
        self.assertEqual(vehicle.fuel_type, "gasoline")
        self.assertTrue(vehicle.vin_decoded_on)
        self.assertFalse(vehicle.vin_decode_note)

    def test_decode_posts_chatter(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-002",
                "vin_sn": ACCORD_VIN,
            }
        )
        before = len(vehicle.message_ids)
        with self._mock_request([ACCORD]):
            vehicle.action_decode_vin()
        self.assertGreater(len(vehicle.message_ids), before)
        body = vehicle.message_ids[0].body
        self.assertIn("Accord", body)
        # The overwrite is what the shop needs to be able to audit afterwards.
        self.assertIn("Prius", body)

    def test_decode_notes_check_digit_complaint(self):
        """ErrorCode 1 still carries usable data, so it is a note not a failure."""
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-003",
                "vin_sn": F150_VIN,
            }
        )
        with self._mock_request([F150]):
            vehicle.action_decode_vin()
        self.assertEqual(vehicle.model_id.nhtsa_model_id, 1801)
        self.assertIn("Check Digit", vehicle.vin_decode_note)
        self.assertFalse(vehicle.vin_check_digit_ok)

    def test_decode_notes_model_missing_from_catalog(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-004",
                "vin_sn": ACCORD_VIN,
            }
        )
        record = dict(ACCORD, ModelID="", Model="Notamodel", Make="NOTAMAKE", MakeID="")
        with self._mock_request([record]):
            vehicle.action_decode_vin()
        # Model is left alone rather than cleared or invented.
        self.assertEqual(vehicle.model_id.name, "Prius")
        self.assertIn("not in the vehicle catalog", vehicle.vin_decode_note)

    def test_invalid_vin_raises_before_any_request(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-005",
                "vin_sn": "NOTAVIN",
            }
        )
        with patch.object(type(self.decoder), "_request") as mocked:
            with self.assertRaises(UserError):
                vehicle.action_decode_vin()
            mocked.assert_not_called()

    def test_unmatched_vin_raises(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-006",
                "vin_sn": ACCORD_VIN,
            }
        )
        with self._mock_request([]):
            with self.assertRaises(UserError):
                vehicle.action_decode_vin()

    def test_batch_decode_multiple_vehicles(self):
        prius = self.env.ref("shop_vehicle_catalog.model_toyota_prius")
        accord = self.Vehicle.create(
            {"model_id": prius.id, "license_plate": "VIN-007", "vin_sn": ACCORD_VIN}
        )
        tesla = self.Vehicle.create(
            {"model_id": prius.id, "license_plate": "VIN-008", "vin_sn": MODEL3_VIN}
        )
        with self._mock_request([ACCORD, MODEL3]) as mocked:
            (accord | tesla).action_decode_vin()
            # One round trip for the pair, not one each.
            self.assertEqual(mocked.call_count, 1)

        self.assertEqual(accord.model_id.name, "Accord")
        self.assertEqual(tesla.model_id.name, "Model 3")
        self.assertEqual(tesla.fuel_type, "electric")

    def test_decode_is_case_insensitive_about_the_vin(self):
        vehicle = self.Vehicle.create(
            {
                "model_id": self.env.ref("shop_vehicle_catalog.model_toyota_prius").id,
                "license_plate": "VIN-009",
                "vin_sn": ACCORD_VIN.lower(),
            }
        )
        with self._mock_request([ACCORD]):
            vehicle.action_decode_vin()
        self.assertEqual(vehicle.model_id.name, "Accord")
