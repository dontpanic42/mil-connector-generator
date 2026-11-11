This is a python script (`connector_gen.py`, no dependencies) that creates 3D-printable MIL-DTL-26482 (Amphenol) plugs from MIL-STD-1669A insert arrangements, as OpenSCAD files.

Input: an arrangement TOML file in `connector-lib/`, e.g. `16-26.toml` (shell size, arrangement, and per contact: x/y position in inch as in MIL-STD-1669A, and contact size). Rows copied from the MIL-STD-1669A PDF into a `.txt` file named like `16-26.txt` can be converted to that format with `connector_gen.py 16-26.txt --size 20`.

Output: an OpenSCAD file with one solid plug body: the shell outline with the polarizing keys, with a hole per contact, extruded to a configurable depth (`--depth`, default 12.32 mm). Viewed from the engaging face (+Z), master key at +Y. A socket insert (`--insert socket`) is mirrored, as MIL-STD-1669A layouts are given for the pin insert face.

The plug has two mounting ears at the rear face with M2 clearance holes (2.5 mm). They hold a retainer plate (second part in the same file) against the rear face, which keeps the contact collars in their counterbores. The `part` customizer variable selects plug, retainer, both side by side (for printing) or assembled (for checking).

Libraries in `connector-lib/`:
- `shell-sizes.toml`: plug shell dimensions per shell size and key widths/angles, from MIL-DTL-26482H figure 5 (page numbers in the file).
- `contact-sizes.toml`: hole diameter in mm per contact size, and optionally a counterbore (diameter, depth) at the rear face for the contact collar. Values are meant to be tuned for 3D print shrinkage.

Reference documents: `MIL-STD-1669A.pdf` (insert arrangements), `MIL-DTL-26482H-1.pdf` (connector dimensions).

After every change, the unit tests should be updated and run successfully.
