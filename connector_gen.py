#!/usr/bin/env python3
"""Generate OpenSCAD models of MIL-DTL-26482 plugs from MIL-STD-1669A insert arrangements.

Input is an arrangement TOML file (see connector-lib/16-26.toml):

    shell = 16
    arrangement = 26

    [contacts]
    A = { x = +0.070, y = +0.300, size = 20 }

with contact positions in inch, as in MIL-STD-1669A, and the contact size.

A text file with lines copied from MIL-STD-1669A can be converted to that
format by passing it as input (--size sets the contact size of all contacts):

    A .000 (0.00) +.268 (6.81)
    E +.165 (4.19) -.212 (5.38)

i.e. label, X offset in inch (mm), Y offset in inch (mm). The mm values in
brackets are unsigned in the datasheets, so the sign is taken from the inch
value; the bracketed mm value is only used as a sanity check. Shell size and
arrangement are taken from a file name like "16-26.txt".

The output is an OpenSCAD file (all dimensions in mm) for 3D printing: one
solid plug body (shell outline with the polarizing keys, insert filled in)
with a hole per contact, extruded to a configurable depth (default 12.32 mm).
Depth and hole diameters are OpenSCAD customizer variables at the top of the
file.

Shell dimensions come from connector-lib/shell-sizes.toml, hole diameters per
contact size from connector-lib/contact-sizes.toml. The model is viewed from
the engaging face (+Z), master key at +Y.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

MM_PER_INCH = 25.4

# Tolerance when comparing the inch value against the bracketed mm value.
# Datasheets round mm to 0.01, so allow a little more than half of that.
MM_CHECK_TOLERANCE = 0.011

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_COORD = rf"({_NUM})\s*\(\s*({_NUM})\s*\)"
LINE_RE = re.compile(rf"^\s*(\S+)\s+{_COORD}\s+{_COORD}\s*$")

LIB_DIR = Path(__file__).resolve().parent / "connector-lib"
SHELL_LIB = LIB_DIR / "shell-sizes.toml"
CONTACT_SIZES = LIB_DIR / "contact-sizes.toml"
ARRANGEMENT_NAME_RE = re.compile(r"^(\d+)-(\d+)")


@dataclass(frozen=True)
class Contact:
    label: str
    x_in: float
    y_in: float
    size: str | None = None


class ParseError(ValueError):
    pass


def _check_mm(inch: float, mm_text: str, lineno: int, axis: str) -> str | None:
    """Return a warning if the bracketed mm value disagrees with the inch value."""
    expected = abs(inch) * MM_PER_INCH
    given = abs(float(mm_text))
    if abs(expected - given) > MM_CHECK_TOLERANCE:
        return (
            f"line {lineno}: {axis} {inch:+.3f} in = {expected:.3f} mm, "
            f"but text says ({mm_text}) mm"
        )
    return None


def parse_contacts(text: str) -> tuple[list[Contact], list[str]]:
    """Parse the input text. Returns (contacts, warnings).

    Blank lines and lines starting with '#' are ignored.
    """
    contacts: list[Contact] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = LINE_RE.match(stripped)
        if not m:
            raise ParseError(f"line {lineno}: cannot parse {line!r}")
        label, x_in, x_mm, y_in, y_mm = m.groups()
        x, y = float(x_in), float(y_in)
        for warning in (_check_mm(x, x_mm, lineno, "X"), _check_mm(y, y_mm, lineno, "Y")):
            if warning:
                warnings.append(warning)
        if label in seen:
            warnings.append(f"line {lineno}: duplicate label {label!r}")
        seen.add(label)
        contacts.append(Contact(label, x, y))

    return contacts, warnings


def load_arrangement(path: Path) -> tuple[str | None, list[Contact]]:
    """Read an arrangement TOML file. Returns (shell size, contacts)."""
    with path.open("rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ParseError(f"{path}: {exc}") from exc
    contacts = []
    for label, c in data.get("contacts", {}).items():
        try:
            contacts.append(Contact(label, float(c["x"]), float(c["y"]), str(c["size"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ParseError(f"{path}: contact {label}: needs x, y and size ({exc})") from exc
    shell = data.get("shell")
    return (str(shell) if shell is not None else None), contacts


def _toml_key(label: str) -> str:
    return label if re.fullmatch(r"[A-Za-z0-9_-]+", label) else f'"{label}"'


def _toml_coord(value: float) -> str:
    return " 0.000" if value == 0 else f"{value:+.3f}"


def arrangement_toml(
    contacts: list[Contact], shell: str | None, arrangement: str | None, source: str
) -> str:
    """Format contacts as an arrangement TOML file."""
    lines = [
        f"# MIL-DTL-26482 insert arrangement, converted from {source}.",
        "# Contact positions in inch (MIL-STD-1669A), viewed from the engaging",
        "# face of the pin insert. size is the contact size.",
        "",
    ]
    if shell:
        lines.append(f"shell = {shell}")
    if arrangement:
        lines.append(f"arrangement = {arrangement}")
    lines += ["", "[contacts]"]
    width = max((len(_toml_key(c.label)) for c in contacts), default=1)
    for c in contacts:
        size = c.size if c.size and c.size.isdigit() else f'"{c.size}"'
        lines.append(
            f"{_toml_key(c.label):<{width}} = {{ x = {_toml_coord(c.x_in)}, "
            f"y = {_toml_coord(c.y_in)}, size = {size} }}"
        )
    return "\n".join(lines) + "\n"




def _nominal(value: float | list[float]) -> float:
    """Mid-point of a [min, max] range, or the value itself."""
    return sum(value) / len(value) if isinstance(value, list) else value


def load_shell(size: str, lib_path: Path = SHELL_LIB) -> dict:
    with lib_path.open("rb") as f:
        lib = tomllib.load(f)
    sizes = [k for k in lib if k != "common"]
    if size not in sizes:
        raise KeyError(f"shell size {size} not in {lib_path} (available: {', '.join(sizes)})")
    return lib[size] | lib.get("common", {})


def load_hole_sizes(path: Path = CONTACT_SIZES) -> dict[str, float]:
    """Hole diameter in mm per contact size."""
    with path.open("rb") as f:
        return {str(k): float(v) for k, v in tomllib.load(f)["hole_dia_mm"].items()}


def load_retainer_holes(path: Path = CONTACT_SIZES) -> dict[str, float]:
    """Retainer plate hole diameter in mm per contact size."""
    with path.open("rb") as f:
        return {str(k): float(v) for k, v in tomllib.load(f)["retainer_hole_dia_mm"].items()}


def load_counterbores(path: Path = CONTACT_SIZES) -> dict[str, tuple[float, float]]:
    """(diameter, depth) in mm of the rear counterbore per contact size."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    dias = data.get("counterbore_dia_mm", {})
    depths = data.get("counterbore_depth_mm", {})
    if dias.keys() != depths.keys():
        raise KeyError(f"{path}: counterbore_dia_mm and counterbore_depth_mm need the same sizes")
    return {str(k): (float(dias[k]), float(depths[k])) for k in dias}


def arrangement_from_filename(path: Path) -> tuple[str | None, str | None]:
    """(shell, arrangement) from a file name like "16-26.txt" -> ("16", "26")."""
    m = ARRANGEMENT_NAME_RE.match(path.stem)
    return (str(int(m.group(1))), str(int(m.group(2)))) if m else (None, None)


def _mm(inch: float) -> str:
    return _num(inch * MM_PER_INCH)


def _num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _scad_name(size: str, prefix: str = "hole_d_") -> str:
    return prefix + re.sub(r"\W", "_", size)


def build_scad(
    contacts: list[Contact],
    shell: dict,
    hole_dia_mm: dict[str, float],
    retainer_holes: dict[str, float],
    depth: float = 12.32,
    title: str = "",
    counterbores: dict[str, tuple[float, float]] | None = None,
) -> str:
    """Build an OpenSCAD model of the plug and its retainer plate.

    The plug is one solid body. Contacts are in inch, viewed from the engaging
    face (top, z = depth). Holes for sizes in counterbores widen at the rear
    face (z = 0). Two mounting ears at the rear face take M2 screws that hold
    the retainer plate against the rear face. Shell OD, key diameter and key
    widths are nominal (mid-tolerance) values.
    """
    counterbores = counterbores or {}
    sizes = sorted({c.size for c in contacts}, key=lambda s: (len(s), s))
    keys = [(shell["master_key_angle"], _nominal(shell["master_key_width"]))]
    keys += [(a, _nominal(shell["minor_key_width"])) for a in shell["minor_key_angles"]]
    hole_lookup = " : ".join(f'size == "{s}" ? {_scad_name(s)}' for s in sizes) + " : undef"
    ret_lookup = (
        " : ".join(f'size == "{s}" ? {_scad_name(s, "ret_d_")}' for s in sizes) + " : undef"
    )
    cb_sizes = [s for s in sizes if s in counterbores]

    def cb_lookup(prefix: str) -> str:
        return "".join(f'size == "{s}" ? {_scad_name(s, prefix)} : ' for s in cb_sizes) + "0"

    out = [
        f"// {title}" if title else "// MIL-DTL-26482 plug",
        "// Generated by connector_gen.py. Dimensions in mm, viewed from the engaging",
        "// face (+Z), master key at +Y.",
        "",
        "/* [Part] */",
        'part = "both"; // [both, plug, retainer, assembled]',
        "",
        "/* [Plug] */",
        f"depth = {_num(depth)};",
        "",
        "/* [Mounting ears] */",
        "screw_hole_d = 2.5; // M2 clearance",
        "ear_wall = 1.5; // material around the screw hole",
        "ear_thickness = 2;",
        "ear_angle = 90; // ears at this angle and +180, clockwise from the master key",
        "",
        "/* [Retainer plate] */",
        "retainer_thickness = 2;",
        *(f"{_scad_name(s, 'ret_d_')} = {_num(retainer_holes[s])}; // contact size {s}" for s in sizes),
        "",
        "/* [Holes] */",
        *(f"{_scad_name(s)} = {_num(hole_dia_mm[s])}; // contact size {s}" for s in sizes),
        "",
        "/* [Counterbores at the rear face] */",
        *(
            line
            for s in cb_sizes
            for line in (
                f"{_scad_name(s, 'cb_d_')} = {_num(counterbores[s][0])}; // contact size {s}",
                f"{_scad_name(s, 'cb_depth_')} = {_num(counterbores[s][1])}; // contact size {s}",
            )
        ),
        "",
        "/* [Resolution] */",
        "$fn = 96;",
        "",
        "/* [Hidden] */",
        f"shell_od = {_mm(_nominal(shell['shell_od']))};  // Y, plug shell OD",
        f"key_od = {_mm(_nominal(shell['key_dia']))};  // X, diameter over keys",
        "",
        "// [angle clockwise from master key, width]",
        "keys = [",
        ",\n".join(f"    [{_num(a)}, {_mm(w)}]" for a, w in keys),
        "];",
        "",
        "// [label, x, y, contact size]",
        "contacts = [",
        ",\n".join(f'    ["{c.label}", {_mm(c.x_in)}, {_mm(c.y_in)}, "{c.size}"]' for c in contacts),
        "];",
        "",
        f"function hole_d(size) = {hole_lookup};",
        f"function cb_d(size) = {cb_lookup('cb_d_')};",
        f"function cb_depth(size) = {cb_lookup('cb_depth_')};",
        f"function ret_d(size) = {ret_lookup};",
        "",
        "ear_w = screw_hole_d + 2 * ear_wall;",
        "screw_r = key_od / 2 + ear_w / 2; // screw holes clear of the keys",
        "",
        """module keyed_profile() {
    intersection() {
        circle(d = key_od);
        union() {
            circle(d = shell_od);
            for (k = keys)
                rotate(-k[0]) translate([-k[1] / 2, 0]) square([k[1], key_od]);
        }
    }
}

module holes() {
    for (c = contacts)
        translate([c[1], c[2], -1]) {
            cylinder(d = hole_d(c[3]), h = depth + 2);
            if (cb_d(c[3]) > 0)
                cylinder(d = cb_d(c[3]), h = cb_depth(c[3]) + 1);
        }
}

module ears() {
    for (a = [ear_angle, ear_angle + 180])
        rotate(-a) hull() {
            circle(d = ear_w);
            translate([0, screw_r]) circle(d = ear_w);
        }
}

module screw_holes(h) {
    for (a = [ear_angle, ear_angle + 180])
        rotate(-a) translate([0, screw_r, -1]) cylinder(d = screw_hole_d, h = h + 2);
}

module plug() {
    difference() {
        union() {
            linear_extrude(depth) keyed_profile();
            linear_extrude(ear_thickness) ears();
        }
        holes();
        screw_holes(depth);
    }
}

// Sits against the rear face of the plug in this orientation (do not flip).
module retainer() {
    difference() {
        linear_extrude(retainer_thickness) union() {
            circle(d = shell_od);
            ears();
        }
        for (c = contacts)
            translate([c[1], c[2], -1]) cylinder(d = ret_d(c[3]), h = retainer_thickness + 2);
        screw_holes(retainer_thickness);
    }
}

if (part == "plug") plug();
else if (part == "retainer") retainer();
else if (part == "assembled") {
    plug();
    translate([0, 0, -retainer_thickness]) retainer();
} else {
    plug();
    // Next to the plug, perpendicular to the ears.
    rotate(-ear_angle - 90) translate([0, key_od / 2 + shell_od / 2 + 5, 0])
        rotate(ear_angle + 90) retainer();
}""",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an OpenSCAD plug model from a MIL-STD-1669A insert arrangement."
    )
    parser.add_argument(
        "input", type=Path, help="arrangement .toml file, or a .txt file to convert to .toml"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output file (default: input name with .scad, or .toml when converting)",
    )
    parser.add_argument(
        "--size", help="contact size for all contacts when converting a .txt file (e.g. 20)"
    )
    parser.add_argument(
        "-d", "--depth", type=float, default=12.32, help="plug depth in mm (default: 12.32)"
    )
    parser.add_argument(
        "-s",
        "--shell",
        metavar="SIZE",
        help="MIL-DTL-26482 shell size (default: shell from the arrangement file)",
    )
    parser.add_argument(
        "-i",
        "--insert",
        choices=("pin", "socket"),
        default="pin",
        help="plug insert type; layouts are given for the pin insert face, "
        "so a socket insert is mirrored (default: pin)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="treat inch/mm mismatches as errors"
    )
    args = parser.parse_args(argv)

    if args.input.suffix == ".txt":
        return convert_txt(args)
    if args.depth <= 0:
        print("error: --depth must be positive", file=sys.stderr)
        return 1

    try:
        file_shell, contacts = load_arrangement(args.input)
    except (OSError, ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not contacts:
        print("error: no contacts found in input", file=sys.stderr)
        return 1

    shell_size = args.shell or file_shell
    if not shell_size:
        print("error: no shell size in the arrangement file, use --shell", file=sys.stderr)
        return 1
    try:
        shell = load_shell(shell_size)
        hole_dia_mm = load_hole_sizes()
        counterbores = load_counterbores()
        retainer_holes = load_retainer_holes()
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 1
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    missing = sorted({c.size for c in contacts} - (hole_dia_mm.keys() & retainer_holes.keys()))
    if missing:
        print(
            f"error: contact size {', '.join(missing)} needs hole_dia_mm and "
            f"retainer_hole_dia_mm in {CONTACT_SIZES}",
            file=sys.stderr,
        )
        return 1

    if args.insert == "socket":
        contacts = [replace(c, x_in=-c.x_in) for c in contacts]

    title = f"MIL-DTL-26482 plug, shell {shell_size}, {args.input.stem}, {args.insert} insert"
    output = args.output or args.input.with_suffix(".scad")
    output.write_text(
        build_scad(
            contacts,
            shell,
            hole_dia_mm,
            retainer_holes,
            depth=args.depth,
            title=title,
            counterbores=counterbores,
        )
    )
    print(
        f"wrote {output}: {len(contacts)} contacts, shell {shell_size}, "
        f"{args.insert} insert, depth {_num(args.depth)} mm"
    )
    return 0


def convert_txt(args: argparse.Namespace) -> int:
    """Convert a MIL-STD-1669A text excerpt to an arrangement TOML file."""
    if not args.size:
        print("error: converting a .txt file needs --size (contact size, e.g. 20)", file=sys.stderr)
        return 1
    try:
        contacts, warnings = parse_contacts(args.input.read_text())
    except (OSError, ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.strict and warnings:
        return 1
    if not contacts:
        print("error: no contacts found in input", file=sys.stderr)
        return 1

    contacts = [Contact(c.label, c.x_in, c.y_in, args.size) for c in contacts]
    shell, arrangement = arrangement_from_filename(args.input)
    output = args.output or args.input.with_suffix(".toml")
    output.write_text(arrangement_toml(contacts, args.shell or shell, arrangement, args.input.name))
    print(f"wrote {len(contacts)} contacts to {output} (shell {args.shell or shell or '?'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
