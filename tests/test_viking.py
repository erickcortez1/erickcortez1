"""Offline tests for the Viking SVG generator."""
import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_viking import (choose_targets, demo_weeks, make_svg, time_anim, geometry,
                             align_weeks, SPRITE_FILES, SPRITES_DIR, build_frame_schedule)


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

    def test_all_approved_frames_are_embedded(self):
        root = ET.fromstring(make_svg(demo_weeks()))
        ns = '{http://www.w3.org/2000/svg}'
        frames = [el for el in root.iter(f'{ns}image')]
        self.assertEqual(len(frames), 12)
        self.assertEqual({el.attrib['id'] for el in frames},
                         {f'frame-{name}' for name in SPRITE_FILES})
        self.assertTrue(all(el.attrib['href'].startswith('data:image/png;base64,')
                            for el in frames))

    def test_png_frames_have_exact_size_and_transparency(self):
        for name in SPRITE_FILES:
            raw = (SPRITES_DIR / f'{name}.png').read_bytes()
            self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual((int.from_bytes(raw[16:20], 'big'),
                              int.from_bytes(raw[20:24], 'big')), (48, 48))

    def test_walk_idle_attack_and_jump_frames_appear_in_schedule(self):
        weeks = demo_weeks()
        pts, total, hits, _, segments = geometry(weeks, choose_targets(weeks))
        timeline = build_frame_schedule(segments, total)
        self.assertEqual(timeline[0][0], 0)
        self.assertEqual(timeline[-1][1], total)
        self.assertTrue({f'attack_{i}' for i in range(1, 5)}.issubset({frame for _, _, frame in timeline}))
        self.assertIn('idle_1', {frame for _, _, frame in timeline})
        self.assertIn('walk_1', {frame for _, _, frame in timeline})
        self.assertTrue(all(abs(a[1] - b[0]) < 0.0001 for a, b in zip(timeline, timeline[1:])))
        self.assertTrue(any(seg['type'] == 'jump' for seg in segments))
        self.assertTrue(pts)
        self.assertTrue(hits)

    def test_demo_cannot_be_mistaken_for_actual_calendar(self):
        self.assertIn('PRÉVIA DEMONSTRATIVA', make_svg(demo_weeks(), demo=True))
        self.assertNotIn('PRÉVIA DEMONSTRATIVA', make_svg(demo_weeks()))

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

    def test_events_in_bounds_and_orthogonal(self):
        points, total, hits, facing, segments = geometry(demo_weeks(), choose_targets(demo_weeks()))
        self.assertTrue(points)
        self.assertTrue(hits)
        self.assertTrue(facing)
        self.assertTrue(all(0 <= t <= total for t, *_ in points))
        self.assertTrue(all(0 <= t <= total for t, *_ in hits))
        # Todo segmento entre keyframes deve ser horizontal, vertical ou estático.
        for (_, x1, y1), (_, x2, y2) in zip(points, points[1:]):
            self.assertTrue(abs(x1 - x2) < 0.001 or abs(y1 - y2) < 0.001)
        self.assertTrue(any(seg['type'] == 'jump' for seg in segments))

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
