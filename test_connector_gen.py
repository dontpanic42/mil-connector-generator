import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from connector_gen import (
    Contact,
    ParseError,
    arrangement_from_filename,
    arrangement_toml,
    build_scad,
    load_arrangement,
    load_counterbores,
    load_hole_sizes,
    load_retainer_holes,
    load_shell,
    main,
    parse_contacts,
)


class ParseTest(unittest.TestCase):
    def test_example_lines(self):
        contacts, warnings = parse_contacts(
            "A .000 (0.00) +.268 (6.81)\nE +.165 (4.19) -.212 (5.38)\n"
        )
        self.assertEqual(warnings, [])
        self.assertEqual([c.label for c in contacts], ["A", "E"])
        self.assertEqual((contacts[1].x_in, contacts[1].y_in), (0.165, -0.212))

    def test_skips_blank_and_comment_lines(self):
        contacts, _ = parse_contacts("# header\n\nA .000 (0.00) .000 (0.00)\n")
        self.assertEqual(len(contacts), 1)

    def test_mm_mismatch_warns(self):
        _, warnings = parse_contacts("A .100 (3.00) .000 (0.00)\n")
        self.assertEqual(len(warnings), 1)

    def test_duplicate_label_warns(self):
        _, warnings = parse_contacts("A .000 (0.00) .000 (0.00)\nA .000 (0.00) .000 (0.00)\n")
        self.assertIn("duplicate", warnings[0])

    def test_bad_line_raises(self):
        with self.assertRaises(ParseError):
            parse_contacts("A .000 .268\n")


LIB = Path(__file__).parent / "connector-lib"
RETAINER = {"20": 2.2, "16": 2.0}


class ScadTest(unittest.TestCase):
    def setUp(self):
        self.contacts = [Contact("A", 0.0, 0.1, "20"), Contact("B", 0.1, -0.1, "16")]
        self.scad = build_scad(
            self.contacts,
            load_shell("16"),
            {"20": 1.2, "16": 1.8},
            RETAINER,
        )
        self.lines = self.scad.splitlines()

    def test_parameters(self):
        self.assertIn("depth = 12.32;", self.lines)
        self.assertIn("hole_d_20 = 1.2; // contact size 20", self.lines)
        self.assertIn("hole_d_16 = 1.8; // contact size 16", self.lines)
        self.assertIn(
            'function hole_d(size) = size == "16" ? hole_d_16 : size == "20" ? hole_d_20 : undef;',
            self.lines,
        )

    def test_depth(self):
        scad = build_scad(self.contacts, load_shell("16"), {"20": 1, "16": 1}, RETAINER, depth=6.5)
        self.assertIn("depth = 6.5;", scad.splitlines())

    def module(self, name):
        start = self.scad.index(f"module {name}()")
        return self.scad[start : self.scad.index("\n}\n", start)]

    def test_plug_is_one_solid_with_ears(self):
        plug = self.module("plug")
        self.assertIn("linear_extrude(depth) keyed_profile();", plug)
        self.assertIn("linear_extrude(ear_thickness) ears();", plug)
        self.assertIn("holes();", plug)
        self.assertIn("screw_holes(depth);", plug)

    def test_retainer(self):
        self.assertIn("retainer_thickness = 2;", self.lines)
        self.assertIn("ret_d_20 = 2.2; // contact size 20", self.lines)
        self.assertIn('function ret_d(size) = size == "16" ? ret_d_16 : size == "20" ? ret_d_20 : undef;', self.lines)
        retainer = self.module("retainer")
        self.assertIn("ears();", retainer)
        self.assertIn("cylinder(d = ret_d(c[3]), h = retainer_thickness + 2);", retainer)
        self.assertIn("screw_holes(retainer_thickness);", retainer)

    def test_ears(self):
        self.assertIn("screw_hole_d = 2.5; // M2 clearance", self.lines)
        self.assertIn("ear_thickness = 2;", self.lines)
        self.assertIn("ear_angle = 90; // ears at this angle and +180, clockwise from the master key", self.lines)
        self.assertIn('part = "both"; // [both, plug, retainer, assembled]', self.lines)

    def test_ear_geometry(self):
        # Screw hole is clear of the keys and the retainer holes hold the collar.
        shell = load_shell("16")
        key_r = sum(shell["key_dia"]) / 2 * 25.4 / 2
        screw_r = key_r + (2.5 + 2 * 1.5) / 2
        self.assertGreater(screw_r - 2.5 / 2, key_r)
        self.assertLess(load_retainer_holes()["20"], 2.52)  # min collar diameter
        self.assertGreater(load_retainer_holes()["20"], 1.98)  # max crimp barrel

    def test_counterbores(self):
        scad = build_scad(
            self.contacts,
            load_shell("16"),
            {"20": 1.2, "16": 1.8},
            RETAINER,
            counterbores={"20": (3.0, 0.85)},
        )
        lines = scad.splitlines()
        self.assertIn("cb_d_20 = 3; // contact size 20", lines)
        self.assertIn("cb_depth_20 = 0.85; // contact size 20", lines)
        self.assertIn('function cb_d(size) = size == "20" ? cb_d_20 : 0;', lines)
        self.assertIn('function cb_depth(size) = size == "20" ? cb_depth_20 : 0;', lines)
        self.assertIn("                cylinder(d = cb_d(c[3]), h = cb_depth(c[3]) + 1);", lines)
        # No counterbores: lookups return 0, so only straight holes are cut.
        self.assertIn("function cb_d(size) = 0;", self.lines)

    def test_counterbore_config(self):
        self.assertEqual(load_counterbores()["20"], (3.0, 0.85))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.toml"
            path.write_text("[counterbore_dia_mm]\n20 = 3.0\n")
            with self.assertRaises(KeyError):
                load_counterbores(path)

    def test_geometry_in_mm(self):
        self.assertIn('    ["A", 0, 2.54, "20"],', self.lines)
        self.assertIn('    ["B", 2.54, -2.54, "16"]', self.lines)
        self.assertIn("shell_od = 21.463;  // Y, plug shell OD", self.lines)
        self.assertIn("    [0, 2.8448],", self.lines)  # master key: 0 deg, .112 in wide
        keys = self.scad[self.scad.index("keys = [") : self.scad.index("];")]
        self.assertEqual(keys.count("["), 6)  # list + 5 keys

    def test_balanced(self):
        for a, b in ("()", "[]", "{}"):
            self.assertEqual(self.scad.count(a), self.scad.count(b), a + b)
        self.assertNotIn(",\n];", self.scad)  # no trailing commas

    def test_contact_sizes_config(self):
        holes = load_hole_sizes()
        _, contacts = load_arrangement(LIB / "16-26.toml")
        self.assertLessEqual({c.size for c in contacts}, holes.keys())
        self.assertTrue(all(d > 0 for d in holes.values()))


class MainTest(unittest.TestCase):
    def run_main(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.scad"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(LIB / "16-26.toml"), "-o", str(out), *args]), 0)
            return out.read_text().splitlines()

    def test_default(self):
        lines = self.run_main()
        self.assertIn("depth = 12.32;", lines)
        self.assertIn('    ["A", 0, 8.1534, "20"],', lines)
        self.assertIn('    ["B", 3.3274, 7.4422, "20"],', lines)

    def test_socket_mirrors_and_keeps_size(self):
        lines = self.run_main("--insert", "socket", "--depth", "3")
        self.assertIn("depth = 3;", lines)
        self.assertIn('    ["B", -3.3274, 7.4422, "20"],', lines)


class ShellTest(unittest.TestCase):
    def test_all_sizes_load(self):
        for size in ("8", "10", "12", "14", "16", "18", "20", "22", "24"):
            shell = load_shell(size)
            self.assertLess(shell["insert_dia_max"], shell["shell_id_min"], size)
            self.assertLess(shell["shell_id_min"], shell["shell_od"][0], size)
            self.assertLess(shell["shell_od"][1], shell["key_dia"][0], size)
            self.assertEqual(shell["minor_key_angles"], [105, 140, 215, 265])

    def test_arrangement_from_filename(self):
        self.assertEqual(arrangement_from_filename(Path("connector-lib/16-26.txt")), ("16", "26"))
        self.assertEqual(arrangement_from_filename(Path("08-98.txt")), ("8", "98"))
        self.assertEqual(arrangement_from_filename(Path("example.txt")), (None, None))

    def test_unknown_size(self):
        with self.assertRaises(KeyError):
            load_shell("9")
        with self.assertRaises(KeyError):
            load_shell("common")


class ArrangementTest(unittest.TestCase):
    def test_toml_round_trip(self):
        contacts, _ = parse_contacts("A .000 (0.00) +.268 (6.81)\nE +.165 (4.19) -.212 (5.38)\n")
        contacts = [c.__class__(c.label, c.x_in, c.y_in, "20") for c in contacts]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "16-26.toml"
            path.write_text(arrangement_toml(contacts, "16", "26", "test"))
            shell, loaded = load_arrangement(path)
        self.assertEqual(shell, "16")
        self.assertEqual(loaded, contacts)

    def test_library_16_26(self):
        shell, contacts = load_arrangement(LIB / "16-26.toml")
        self.assertEqual(shell, "16")
        self.assertEqual(len(contacts), 26)
        self.assertEqual({c.size for c in contacts}, {"20"})

    def test_library_20_41(self):
        shell, contacts = load_arrangement(LIB / "20-41.toml")
        self.assertEqual(shell, "20")
        self.assertEqual(len(contacts), 41)
        self.assertEqual({c.size for c in contacts}, {"20"})
        by_label = {c.label: c for c in contacts}
        self.assertEqual((by_label["p"].x_in, by_label["p"].y_in), (0.065, -0.135))
        self.assertEqual((by_label["t"].x_in, by_label["t"].y_in), (0.0, 0.0))
        # All contacts fit inside the insert.
        r_max = load_shell("20")["insert_dia_max"] / 2
        self.assertTrue(all((c.x_in**2 + c.y_in**2) ** 0.5 < r_max for c in contacts))

    def test_missing_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.toml"
            path.write_text("[contacts]\nA = { x = 0.0, y = 0.1 }\n")
            with self.assertRaises(ParseError):
                load_arrangement(path)


if __name__ == "__main__":
    unittest.main()
