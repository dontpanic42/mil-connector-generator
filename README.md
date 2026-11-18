# MIL-DTL-26482 connector generator

Generates 3D-printable plug inserts for MIL-DTL-26482 (Amphenol PT/MS3116-style)
circular connectors, as OpenSCAD files. Contact layouts come from MIL-STD-1669A
insert arrangements; shell and key dimensions from MIL-DTL-26482H.

Each generated file contains two parts:

- **Plug**: the shell outline with the polarizing keys (master key at +Y), a hole
  per contact with a counterbore at the rear for the contact collar, and two
  mounting ears with M2 clearance holes.
- **Retainer plate**: screws onto the ears and holds the contact collars in their
  counterbores.

## Requirements

- Python 3.11 or newer (uses `tomllib`, no other dependencies)
- [OpenSCAD](https://openscad.org/) to render and export the model

## Usage

```sh
python3 connector_gen.py connector-lib/16-26.toml
```

This writes `connector-lib/16-26.scad`. Open it in OpenSCAD and use the
Customizer to choose what to show with `part`:

| `part`      | Shows                                             |
|-------------|---------------------------------------------------|
| `both`      | plug and retainer side by side, ready to print    |
| `plug`      | plug only                                         |
| `retainer`  | retainer plate only                               |
| `assembled` | retainer mounted on the plug, for checking the fit |

The Customizer also exposes depth, hole and counterbore diameters, ear and
retainer dimensions, so you can tune a print without regenerating.

Options:

| Option                   | Description                                                          |
|--------------------------|----------------------------------------------------------------------|
| `-o`, `--output FILE`    | output file (default: input name with `.scad`)                       |
| `-d`, `--depth MM`       | plug depth (default 12.32 mm)                                        |
| `-s`, `--shell SIZE`     | override the shell size from the arrangement file                    |
| `-i`, `--insert pin\|socket` | socket inserts are mirrored, as MIL-STD-1669A shows the pin insert face |
| `--strict`               | treat inch/mm mismatches in `.txt` input as errors                   |

## Included arrangements

| File          | Shell | Contacts      |
|---------------|-------|---------------|
| `10-6.toml`   | 10    | 6 × size 20   |
| `16-26.toml`  | 16    | 26 × size 20  |
| `20-41.toml`  | 20    | 41 × size 20  |

## Adding an arrangement

1. Copy the contact rows from MIL-STD-1669A into a text file named after the
   arrangement (`<shell>-<arrangement>.txt`), one contact per line:

   ```
   A .000 (0.00) +.130 (3.30)
   B +.113 (2.87) +.065 (1.65)
   ```

2. Convert it to TOML, giving the contact size:

   ```sh
   python3 connector_gen.py 10-6.txt --size 20 -o connector-lib/10-6.toml
   ```

   The converter cross-checks the inch and mm columns and warns about
   mismatches. The standard has a few misprints in the mm values; the inch
   values are used.

3. Generate the model: `python3 connector_gen.py connector-lib/10-6.toml`

Arrangements with mixed contact sizes can be edited by hand: each contact in
the TOML file has its own `size`.

## Libraries

All in `connector-lib/`:

- `shell-sizes.toml`: plug shell, key and receptacle dimensions per shell size
  (8–24) from MIL-DTL-26482H figure 5, with page references.
- `contact-sizes.toml`: per contact size, the hole diameter, rear counterbore
  (diameter and depth) and retainer hole diameter, all in mm. **Tune these for
  your printer**: holes usually print undersize.

## Printing and assembly

- Print the plug with the engaging face up; the counterbores and ears are on
  the bed side.
- The walls between neighbouring counterbores are thin (about 0.3 mm with the
  default 3 mm counterbore on 3.3 mm pitch), so use a fine nozzle/layer height.
- Insert the crimped contacts from the rear, place the retainer plate over the
  wires and fix it with two M2 screws and nuts (M2×6 or M2×8).

## Tests

```sh
python3 -m unittest
```

## References

- MIL-STD-1669A: insert arrangements for MIL-DTL-26482 connectors
- MIL-DTL-26482H: connector dimensions (figure 5, intermateability)

The standards are not included in this repository.
