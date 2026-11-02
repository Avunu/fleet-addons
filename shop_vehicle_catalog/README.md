# Shop Vehicle Catalog

A US vehicle make/model catalog for Odoo 18 Fleet, covering light-duty autos
and Class 6-8 commercial trucks, with a Year/Make/Model picker on the vehicle
form.

Core Odoo ships 66 brands and **zero** models, and its brand list is
Euro-centric — no GMC, RAM, Mercury, Plymouth, Saturn or Peterbilt. Without
this module every customer vehicle is hand-typed, so spellings drift and repair
history cannot be grouped by model.

## What it does

- **2,387 models across 87 makes** (1981–2027), loaded as Odoo CSV data files.
  Each model carries its production years, so the Model dropdown can be filtered
  to what was actually sold in the year the advisor entered.
- **Reuses core Odoo's brands** where they exist (48 of 87 makes), so those
  brands keep their logos. Only the 39 makes core lacks get new records.
- **`fleet.vehicle.model`** gains `year_start` / `year_end` (indexed, they drive
  the picker domain), `year_set` (the exact years including gaps), and
  `nhtsa_model_id`. `covers_year()` answers gap-accurate membership.
- **`fleet.vehicle`** gains `model_year_int`, a numeric mirror of the existing
  `model_year` Char, because a Char cannot be compared against Integer year
  bounds in a view domain.
- **Year/Make/Model form**: Model Year sits above Model, and picking a year
  narrows the model list. A mismatch warns but never blocks — grey-market
  imports and re-titled vehicles legitimately fall outside the catalog.

## Design notes

**`vehicle_type` is deliberately left at `'car'` on every catalog record.**
It is tempting to `selection_add` a `truck` value, but core fleet views gate
~15 fields behind `invisible="vehicle_type != 'car'"`, including the
**odometer**, transmission, seats and doors
(`fleet/views/fleet_vehicle_views.xml`). Any new value silently hides the
odometer field, which the repair workflow depends on. The car/SUV/truck
classification lives in `category_id` (`fleet.vehicle.model.category`) instead,
which has no behaviour attached to it anywhere in core.

**The picker domain uses `year_start`/`year_end`, not `year_set`.** Only the
two integers are indexed, and a compressed set cannot be expressed as a domain.
The consequence is that a model with a gap in its history (VW Golf R:
`2013,2016-2020,2022-2027`) still appears when you type a year inside the gap.
The onchange warning is what catches that case.

**Data files are updatable (no `noupdate`)** so a regenerated catalog flows
through on `-u`. Manual edits to a catalog record therefore revert on update,
which is the right behaviour for reference data. If a model ever disappears
upstream, module update tries to delete it and will raise when a `fleet.vehicle`
still points at it (`model_id` is required) — handle that by hand.

## Regenerating the data

The data comes from [open-vehicle-db](https://github.com/plowman/open-vehicle-db),
which derives it from the NHTSA vPIC API (US government, public domain).

Upstream's curation lists excluded most of what a repair shop needs: a typo in
`WHITE_LIST` (`"volkwagen"`) dropped Volkswagen entirely, and every commercial
truck make except Peterbilt was blacklisted. The fix lives on the
`commercial-makes` branch of <https://github.com/Avunu/open-vehicle-db>,
which adds VW, Genesis, Polestar, Eagle, VinFast and twelve Class 6-8 makes —
70 → 87 makes, 1,678 → 2,387 models.

To refresh:

```sh
# 1. Update the source (per-make is much faster than a full sweep)
cd /path/to/open-vehicle-db
uv run ./scripts/update_car_data.py toyota

# 2. Regenerate the Odoo data files and commit the diff
cd /path/to/fleet-addons/shop_vehicle_catalog
./tools/generate_catalog.py /path/to/open-vehicle-db

# 3. Apply
python odoo/odoo-bin -c odoo.conf -d <db> -u shop_vehicle_catalog --stop-after-init
```

The generator parses core Odoo's `fleet_cars_data.xml` for brand XML IDs rather
than hardcoding them, and fails loudly on any make that resembles a core brand
without matching it — there is no uniqueness constraint on brand name, so a
missed alias would silently split a brand's models across two records.

## Tests

```sh
python odoo/odoo-bin -c odoo.conf -d <testdb> -i shop_vehicle_catalog \
  --test-enable --test-tags /shop_vehicle_catalog --stop-after-init
```

## Not included

- **VIN decode.** NHTSA vPIC `DecodeVin` is free and returns make/model/year
  plus engine and body style from the VIN already stored in
  `fleet.vehicle.vin_sn`. For a shop that beats any static catalog for data
  entry accuracy, and it is the natural place engine data would enter.
- **Trims/styles.** open-vehicle-db has 9,960 of them, but they carry no engine
  or displacement data, so they add picker friction without parts-lookup value.
