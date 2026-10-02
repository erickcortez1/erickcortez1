"""Offline tests for the Viking SVG generator."""
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_viking import choose_targets, demo_weeks, make_svg, time_anim, geometry, align_weeks


class VikingTests(unittest.TestCase):
    def test_demo_calendar_shape(self):
        weeks = demo_weeks()
        self.assertEqual(len(weeks), 53)
        self.assertTrue(all(len(week) == 7 for week in weeks))

    def test_svg_is_valid_xml(self):
        svg = make_svg(demo_weeks())
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertIn("viking-motion", svg)
        self.assertIn("animateTransform", svg)
        self.assertIn("#26a641", svg)

    def test_partial_week_aligns_to_sunday(self):
        monday = {"date": "2026-09-28", "contributionCount": 4, "contributionLevel": "FOURTH_QUARTILE"}
        aligned = align_weeks([[monday]])
        self.assertEqual(len(aligned[0]), 7)
        self.assertEqual(aligned[0][0]["contributionCount"], 0)
        self.assertEqual(aligned[0][1]["contributionCount"], 4)

    def test_hits_only_active_cells(self):
        weeks = demo_weeks()
        for c, r in choose_targets(weeks):
            self.assertGreater(weeks[c][r]["contributionCount"], 0)

    def test_events_in_bounds(self):
        points, total, hits, facing = geometry(demo_weeks(), choose_targets(demo_weeks()))
        self.assertTrue(points)
        self.assertTrue(hits)
        self.assertTrue(facing)
        self.assertTrue(all(0 <= t <= total for t, *_ in points))
        self.assertTrue(all(0 <= t <= total for t, *_ in hits))

    def test_no_contribution_fallback(self):
        weeks = demo_weeks()
        for week in weeks:
            for day in week:
                day.update(contributionCount=0, contributionLevel="NONE")
        svg = make_svg(weeks)
        ET.fromstring(svg)
        self.assertIn("Sem contribuições públicas", svg)

    def test_smil_keytimes_ordered(self):
        result = time_anim("opacity", [(0, "1"), (1, "0"), (2, "1")], 2)
        self.assertIn('keyTimes="0.000000;0.500000;1.000000"', result)


if __name__ == "__main__":
    unittest.main()
