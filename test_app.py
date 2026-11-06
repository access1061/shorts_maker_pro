import unittest
from app import audio_offset_filter, crop_positions, selection_rect, video_start_time


class SelectionTests(unittest.TestCase):
    def test_free_selection_clamps_and_handles_reverse_drag(self):
        self.assertEqual(selection_rect((500, 500), (-20, 100), 1920, 1080, False), (0, 100, 500, 400))

    def test_vertical_selection_fits_drag_and_screen(self):
        x, y, width, height = selection_rect((100, 100), (900, 1080), 1920, 1080, True)
        self.assertEqual((x, y), (100, 100))
        self.assertLessEqual(width, 800)
        self.assertLessEqual(height, 980)
        self.assertAlmostEqual(width / height, 9 / 16, delta=0.002)


class CropTests(unittest.TestCase):
    def test_tracking_is_smoothed_and_bounded(self):
        width, points = crop_positions([(0, 0), (1, 1920), (2, -500)], 1920, 1080)
        self.assertEqual(width, 606)
        self.assertGreater(points[1][1], points[0][1])
        self.assertTrue(all(0 <= x <= 1920 - width for _, x in points))

    def test_portrait_monitor_is_not_cropped_outside_frame(self):
        width, points = crop_positions([(1, 10000)], 600, 1920)
        self.assertEqual(width, 600)
        self.assertEqual(points[0][1], 0)


class AudioSyncTests(unittest.TestCase):
    def test_video_start_is_read_from_gdigrab_log(self):
        log = "Input #0, gdigrab, from 'desktop':\n  Duration: N/A, start: 1793945724.507213, bitrate: 1 kb/s\n"
        self.assertEqual(video_start_time(log), 1793945724.507213)
        self.assertIsNone(video_start_time("no input"))

    def test_late_audio_is_delayed_and_early_audio_is_trimmed(self):
        self.assertEqual(audio_offset_filter(0.25), "adelay=250:all=1,apad")
        self.assertEqual(audio_offset_filter(-0.4), "atrim=start=0.400,asetpts=PTS-STARTPTS,apad")


if __name__ == "__main__":
    unittest.main()
