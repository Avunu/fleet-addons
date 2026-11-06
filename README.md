# Avunu fleet addons

Odoo 18.0 modules for vehicle data in Fleet: a catalogue of US makes and models with a Year/Make/Model picker, and VIN decoding against the free NHTSA vPIC API. They are built and maintained by [Avunu LLC](https://avunu.net) and published for anyone to use. They extend Odoo's core Fleet app, as [OCA/fleet](https://github.com/OCA/fleet) does, and need no OCA modules.

## Modules

| Module | What it does | Licence |
| --- | --- | --- |
| [`shop_vehicle_catalog`](shop_vehicle_catalog/README.md) | A US make and model catalogue for Fleet, covering light-duty autos and Class 6-8 trucks, with each model's production years and a Year/Make/Model picker on the vehicle form; reuses core Odoo's brands where they exist | AGPL-3.0-or-later |
| [`shop_vehicle_vin`](shop_vehicle_vin/README.md) | Decodes a VIN against the NHTSA vPIC API and fills in the vehicle's model, year, engine, drivetrain and body, from a button on the vehicle form or in bulk from the list; warns on a bad check digit and notes what changed in the chatter | AGPL-3.0-or-later |

## Branches

`develop` is the default branch and where pull requests go. Its code targets Odoo 18.0, the series named in `.odoo-series`. `18.0` follows `develop` automatically (a workflow fast-forwards it after every push) and is the branch to install or pin. When a newer Odoo series is maintained, it gets its own branch (`19.0`, …) and changes flow up to it from `develop`.

## Install

Requires Odoo 18.0 and a PostgreSQL database. Pick the module or modules you want; each pulls in the modules it depends on (see below), all of which are in Odoo core or in this repository.

With a plain Odoo checkout, clone this repository on its `18.0` branch and add it to the addons path:

```sh
git clone --branch 18.0 https://github.com/Avunu/fleet-addons.git
odoo-bin --addons-path=odoo/addons,/path/to/fleet-addons \
  -d <database> -i <module> --stop-after-init
```

With [odoo-nix](https://github.com/Avunu/odoo-nix), add the repository from the dev shell. `odoo module add` accepts an `owner/repo` and a branch, adds it as a submodule, and the addons path is regenerated from the folders present (run `direnv reload` afterwards):

```sh
odoo module add Avunu/fleet-addons 18.0
```

## Dependencies

Each module's `__manifest__.py` is the source of truth. Both modules build on Odoo's core `fleet` module and need nothing from OCA or other third parties.

| Module | Needs from OCA or others | Python packages |
| --- | --- | --- |
| `shop_vehicle_catalog` | none beyond core | none |
| `shop_vehicle_vin` | `shop_vehicle_catalog` (this repository), whose NHTSA IDs it matches decoded models against | none |

`shop_vehicle_vin` calls the [NHTSA vPIC API](https://vpic.nhtsa.dot.gov/api/) when you decode a VIN, so the Odoo server needs outbound HTTPS access to it; the service is free and needs no credentials. Its base URL and timeout are system parameters, listed in its README.

`shop_vehicle_catalog` ships its catalogue as CSV data files. The generator in its `tools/` folder, which rebuilds them from a checkout of the `commercial-makes` branch of [Avunu/open-vehicle-db](https://github.com/Avunu/open-vehicle-db), a fork of [open-vehicle-db](https://github.com/plowman/open-vehicle-db), is only needed to refresh the data, not to run the module. See its README.

## Development

The repository carries its own development environment, built by [odoo-nix](https://github.com/Avunu/odoo-nix) in addons mode. OCB and the repositories these modules depend on are flake inputs pinned in `flake.lock`, and the Python environment is locked in `nix/`. You need Nix with flakes, and optionally direnv.

```sh
git clone https://github.com/Avunu/fleet-addons.git && cd fleet-addons
direnv allow                  # or: nix develop --no-pure-eval
devenv up                     # PostgreSQL, Odoo and Mailpit
odoo db provision             # a database with every module here installed
odoo test shop_vehicle_catalog
```

After `nix flake update`, or when a module gains a `depends` or a Python requirement, run `odoo project relock` and commit `flake.lock` and `nix/`. A new dependency on another repository also needs its input and an `externalSources` entry in `flake.nix`. See odoo-nix's [A repository of addons](https://github.com/Avunu/odoo-nix/blob/main/docs/scaffolding/addons-repository.md).

## Tests

Odoo runs a module's tests when you install or update it with `--test-enable`. Select a module's tests with a `--test-tags` filter and use a throwaway database:

```sh
odoo-bin -c odoo.conf -d <testdb> -i <module> \
  --test-enable --test-tags /<module> --stop-after-init
```

Both modules have automated tests. `shop_vehicle_vin`'s tests never touch the network: the HTTP request is patched and fed captured vPIC responses.

## Licence

Both modules are licensed under the [GNU Affero General Public License v3.0 or later](LICENSE). The licence of each module is also stated in its `__manifest__.py` (`AGPL-3`, Odoo's identifier for version 3).

Neither module vendors third-party code. The make and model data in `shop_vehicle_catalog` is generated from open-vehicle-db, which derives it from the NHTSA vPIC API (US government data, public domain).

## Provenance

Both modules were first developed in a private Avunu project and imported here.
