#!/usr/bin/env python3
# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Regenerate the Odoo catalog data files from an open-vehicle-db checkout.

Run this by hand when open-vehicle-db has new data, then commit the diff --
the generated files are the deliverable, not this script, and nothing runs it
at install time.

    ./tools/generate_catalog.py /path/to/open-vehicle-db

Writes three CSVs into data/. Odoo loads a data file named after the model it
fills, with an ``id`` column for XML IDs and ``field/id`` for many2one refs,
which is far more compact than the equivalent XML and diffs one line per model.

Brands are the fiddly part. Core Odoo ships 66 brands in
fleet/data/fleet_cars_data.xml, and reusing them matters because they carry
logos. Most makes match one on a normalised name; three need an explicit alias.
There is no uniqueness constraint on brand name in core, so a make that should
have matched but didn't would silently create a duplicate -- hence the
strictness check in verify_alias_map().
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = MODULE_ROOT / "data"
# fleet-addons/shop_vehicle_catalog/tools/ -> an odoo checkout beside fleet-addons/
CORE_FLEET_DATA = (
    MODULE_ROOT.parent.parent / "odoo/addons/fleet/data/fleet_cars_data.xml"
)


def read_core_brands(path: Path) -> dict[str, str]:
    """Map core Odoo's brand display names to their XML IDs, read from source.

    Parsed rather than transcribed because getting one ID wrong is invisible
    until install: brand_rolls-royce has a hyphen, and every other one does not.
    """
    if not path.exists():
        raise SystemExit(f"cannot find core fleet brands at {path}")
    pairs = re.findall(
        r'<record id="([^"]+)" model="fleet\.vehicle\.model\.brand">\s*'
        r'<field name="name">([^<]+)</field>',
        path.read_text(),
    )
    if not pairs:
        raise SystemExit(
            f"no brand records matched in {path} -- has the format changed?"
        )
    return {name.strip(): xmlid for xmlid, name in pairs}


# Makes whose name does not normalise onto the core brand they belong to.
# Keyed by open-vehicle-db make_slug, valued by core XML ID.
BRAND_ALIASES = {
    "alfa_romeo": "brand_alfa",
    "mercedes_benz": "brand_mercedes",
    "tesla": "brand_tesla_motors",
}

# Makes that must NOT reuse a core brand even though the names look close.
# VOLVO TRUCK and MITSUBISHI FUSO are separate manufacturers from the Volvo and
# Mitsubishi that make cars, and a shop needs to tell an XC90 from a VNL apart
# at the brand level. RAM is a Stellantis truck marque, not Rambler.
BRAND_NO_REUSE = {"volvo_truck", "mitsubishi_fuso", "ram"}

# NHTSA vehicle types -> fleet.vehicle.model.category. Deliberately NOT mapped
# onto fleet.vehicle.model.vehicle_type: core fleet views gate the odometer,
# transmission, seats and doors fields behind `invisible="vehicle_type != 'car'"`,
# so adding a selection value would hide the odometer on every truck.
CATEGORIES = {
    "car": ("category_car", "Car", 10),
    "mpv": ("category_mpv", "SUV / Van", 20),
    "truck": ("category_truck", "Truck", 30),
}


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


CORE_BRANDS = read_core_brands(CORE_FLEET_DATA)
CORE_BY_NORM = {normalise(name): xmlid for name, xmlid in CORE_BRANDS.items()}
_ALIAS_TARGETS = set(BRAND_ALIASES.values()) - set(CORE_BRANDS.values())
if _ALIAS_TARGETS:
    raise SystemExit(
        f"BRAND_ALIASES point at XML IDs core fleet does not define: {sorted(_ALIAS_TARGETS)}"
    )


# NHTSA shouts every make name, and naive title-casing gets a handful wrong.
# Only makes that need a new brand record have to appear here -- the rest reuse
# a core Odoo brand and keep its spelling.
MAKE_DISPLAY_NAMES = {
    "AM GENERAL": "AM General",
    "BMW": "BMW",
    "DELOREAN": "DeLorean",
    "GMC": "GMC",
    "MCLAREN": "McLaren",
    "RAM": "RAM",
    "UD": "UD",
    "VINFAST": "VinFast",
}


def title_case_make(make_name: str) -> str:
    """Render a shouted NHTSA make name the way a person would write it."""
    if make_name in MAKE_DISPLAY_NAMES:
        return MAKE_DISPLAY_NAMES[make_name]
    return " ".join(
        "-".join(part.capitalize() for part in word.split("-"))
        for word in make_name.split()
    )


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def year_bounds(year_set: str) -> tuple[int, int]:
    years = []
    for chunk in year_set.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        start, _, end = chunk.partition("-")
        years.append(int(start))
        years.append(int(end) if end else int(start))
    return (min(years), max(years)) if years else (0, 0)


def verify_alias_map(makes: list[dict]) -> None:
    """Fail loudly on any make that would silently duplicate a core brand.

    A make whose name normalises onto a core brand must either reuse it or be
    listed in BRAND_NO_REUSE. Anything else means a new brand record lands next
    to an identical core one, with no SQL constraint to catch it.
    """
    problems = []
    for make in makes:
        slug = make["make_slug"]
        if slug in BRAND_ALIASES or slug in BRAND_NO_REUSE:
            continue
        norm = normalise(make["make_name"])
        if norm in CORE_BY_NORM:
            continue
        # A near-miss: the make shares a prefix with a core brand but does not
        # match it. Worth a human look rather than a silent new record.
        for core_norm in CORE_BY_NORM:
            if norm != core_norm and (
                norm.startswith(core_norm) or core_norm.startswith(norm)
            ):
                problems.append(
                    f"  {make['make_name']!r} ({slug}) resembles core brand "
                    f"{CORE_BY_NORM[core_norm]!r} but does not match it. "
                    f"Add it to BRAND_ALIASES or BRAND_NO_REUSE."
                )
    if problems:
        raise SystemExit(
            "Ambiguous brand mapping:\n" + "\n".join(sorted(set(problems)))
        )


def brand_ref(make: dict) -> tuple[str, bool]:
    """Return (XML ID to reference, whether we have to create it)."""
    slug = make["make_slug"]
    if slug in BRAND_ALIASES:
        return f"fleet.{BRAND_ALIASES[slug]}", False
    if slug not in BRAND_NO_REUSE:
        core = CORE_BY_NORM.get(normalise(make["make_name"]))
        if core:
            return f"fleet.{core}", False
    return f"make_{slug}", True


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.relative_to(MODULE_ROOT)}: {len(rows)} rows")


def main(source: Path) -> None:
    makes = read_csv(source / "makes.csv")
    models = read_csv(source / "models.csv")
    verify_alias_map(makes)

    DATA_DIR.mkdir(exist_ok=True)
    print(f"Generating from {source} ({len(makes)} makes, {len(models)} models)")

    write_csv(
        DATA_DIR / "fleet.vehicle.model.category.csv",
        ["id", "name", "sequence"],
        [
            {"id": xmlid, "name": name, "sequence": sequence}
            for xmlid, name, sequence in sorted(CATEGORIES.values(), key=lambda c: c[2])
        ],
    )

    brand_rows = []
    brand_xmlid_by_slug = {}
    for make in sorted(makes, key=lambda m: m["make_slug"]):
        ref, must_create = brand_ref(make)
        brand_xmlid_by_slug[make["make_slug"]] = ref
        if must_create:
            brand_rows.append(
                {
                    "id": ref,
                    "name": title_case_make(make["make_name"]),
                    "nhtsa_make_id": make["make_id"],
                }
            )
    write_csv(
        DATA_DIR / "fleet.vehicle.model.brand.csv",
        ["id", "name", "nhtsa_make_id"],
        brand_rows,
    )
    print(f"  ({len(makes) - len(brand_rows)} makes reuse a core Odoo brand)")

    model_rows = []
    for model in sorted(models, key=lambda m: (m["make_slug"], m["model_slug"])):
        start, end = year_bounds(model["years"])
        category = CATEGORIES.get(model["vehicle_type"])
        model_rows.append(
            {
                "id": f"model_{model['make_slug']}_{model['model_slug']}",
                "name": model["model_name"],
                "brand_id/id": brand_xmlid_by_slug[model["make_slug"]],
                "category_id/id": category[0] if category else "",
                "year_start": start,
                "year_end": end,
                "year_set": model["years"],
                "nhtsa_model_id": model["model_id"],
                # Left at 'car' on purpose -- see the CATEGORIES comment.
                "vehicle_type": "car",
            }
        )
    write_csv(
        DATA_DIR / "fleet.vehicle.model.csv",
        [
            "id",
            "name",
            "brand_id/id",
            "category_id/id",
            "year_start",
            "year_end",
            "year_set",
            "nhtsa_model_id",
            "vehicle_type",
        ],
        model_rows,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <path to open-vehicle-db checkout>")
    data_dir = Path(sys.argv[1]).expanduser().resolve()
    if data_dir.name != "data":
        data_dir = data_dir / "data"
    if not (data_dir / "makes.csv").exists():
        raise SystemExit(f"no makes.csv under {data_dir}")
    main(data_dir)
