# Shop Vehicle VIN Decode

Fills a vehicle in from its VIN using the [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/)
decoder — a free US government service that needs no credentials.

For a repair shop this beats a static catalog for data entry: the VIN is
already on the car, and it resolves the exact year/make/model *plus* engine
displacement, cylinder count, drive type and body class — the specs that
actually matter when ordering parts, and which no free make/model dataset
carries.

## What it does

- **"Decode VIN" button** next to the VIN field on the vehicle form. Fills
  model, model year, engine, drivetrain and body, then posts a chatter entry
  showing what changed — a decode overwrites fields, so the shop needs to be
  able to see afterwards what the VIN said versus what someone typed.
- **Check-digit warning.** The 9th VIN character is a checksum of the other 16.
  A mismatch shows an inline warning but never blocks: some manufacturers
  don't follow the standard, and NHTSA decodes those VINs anyway.
- **Batch backfill.** Select vehicles in the list view → Actions → Decode VIN.
  Batched 50 at a time against `DecodeVINValuesBatch`, so backfilling an
  existing customer base is a handful of requests, not one per vehicle.
- **Shape validation before the network call**, so a typo'd VIN gets an
  immediate, specific message ("VINs never contain O — that's usually a misread
  0") rather than a round trip and a shrug.

## How model matching works

This is why the module depends on `shop_vehicle_catalog`: that module stamps
`nhtsa_make_id` / `nhtsa_model_id` onto brands and models, and vPIC returns
those same IDs. Matching is by ID, not by name.

Three attempts, most reliable first:

1. `ModelID` → `fleet.vehicle.model.nhtsa_model_id` — exact.
2. `MakeID` → brand, then model name within that brand.
3. Same, ignoring punctuation (NHTSA writes `F-150`; a catalog might hold `F150`).

**It never creates catalog records.** The catalog is module-managed data, and a
model invented at runtime would sit alongside it with no provenance. When
nothing matches, the vehicle's model is left alone and the decode note says
what was decoded so the advisor can pick or create one.

## Field mapping notes

- **Fuel type.** NHTSA splits this across two fields — a Prius reports
  `FuelTypePrimary` "Gasoline" like any other car, and only
  `ElectrificationLevel` "Strong HEV" makes it a hybrid. Both are consulted.
- **Transmission.** Core fleet only knows manual vs automatic. A DCT or CVT maps
  to automatic (which is what the driver experiences) and the full style string
  is kept in `vin_transmission_style`, so nothing is lost.
- **`vin_` prefix.** Every decoded spec field is prefixed. It marks provenance
  on the form — these came from the VIN, not from someone's memory — and keeps
  the module out of the way of OCA fleet modules that add spec fields.
- **Sparse decodes never blank existing data.** Only keys with a value are
  written, and NHTSA's "Not Applicable" filler is treated as absent.

Specs land on their own **VIN Specifications** notebook page rather than in
core's Engine group, which is gated on `vehicle_type == 'car'` and would hide
all of it on anything classified otherwise (see the `vehicle_type` trap in
`shop_vehicle_catalog`).

## Configuration

Two `ir.config_parameter` entries, `noupdate` so local changes survive updates:

| Key | Default |
|---|---|
| `shop_vehicle_vin.base_url` | `https://vpic.nhtsa.dot.gov/api/vehicles` |
| `shop_vehicle_vin.timeout` | `20` (seconds) |

Decoding runs **synchronously** — it sits behind a button someone is waiting on,
and vPIC answers in well under a second. If a large backfill ever needs to run
unattended, wrap `shop.vin.decoder.decode()` in a `queue_job`.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i shop_vehicle_vin \
  --test-enable --test-tags /shop_vehicle_vin --stop-after-init
```

26 tests, none of which touch the network: `shop.vin.decoder._request` is
patched and fed captured vPIC responses. The fixture VINs are public samples (the Model 3 one is synthetic), and the
F-150 one genuinely fails its checksum — which is how the check-digit path
gets exercised against NHTSA's own verdict.

## Limitations

- **US-market vehicles only.** vPIC decodes what NHTSA has on file; a
  grey-market import will return nothing and raise.
- **VIN decode gives the build spec, not the current state.** An engine swap or
  a transmission rebuild won't show up. Treat the decoded specs as the starting
  point, not the last word.
