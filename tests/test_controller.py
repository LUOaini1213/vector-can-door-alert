"""Contract tests calculated from exact timestamps and integer speed thresholds."""
import unittest

from door_alert.controller import Controller
from door_alert.protocol import Frame, encode_doors, encode_vehicle


def state(snapshot):
    return snapshot.warning, snapshot.data_fault, snapshot.reason


class ControllerTiming(unittest.TestCase):
    def test_initial_state_without_inputs(self):
        snapshot = Controller().tick(0)
        self.assertEqual(state(snapshot), (False, True, 1))
        self.assertIsNone(snapshot.pending_since_ms)
        self.assertIsNone(snapshot.speed_kmh)
        self.assertIsNone(snapshot.door_mask)

    def test_one_stream_cannot_start_debounce(self):
        for frame in (encode_vehicle(0, 20, True), encode_doors(0, 1)):
            with self.subTest(message_id=frame.arbitration_id):
                controller = Controller()
                controller.receive(frame)
                self.assertEqual(state(controller.tick(0)), (False, True, 1))

    def test_exact_debounce_boundary_and_active_hysteresis(self):
        controller = Controller()
        controller.receive(encode_vehicle(0, 5, True))
        controller.receive(encode_doors(0, 8))
        first = controller.tick(0)
        self.assertEqual(state(first), (False, False, 5))
        self.assertEqual(first.pending_since_ms, 0)
        for timestamp in range(10, 200, 10):
            self.assertEqual(state(controller.tick(timestamp)), (False, False, 5))
        active = controller.tick(200)
        self.assertEqual(state(active), (True, False, 6))
        self.assertIsNone(active.pending_since_ms)
        controller.receive(encode_vehicle(210, 3.01, True))
        self.assertEqual(state(controller.tick(210)), (True, False, 6))
        controller.receive(encode_vehicle(220, 3, True))
        self.assertEqual(state(controller.tick(220)), (False, False, 4))
        controller.receive(encode_vehicle(230, 4.99, True))
        self.assertEqual(state(controller.tick(230)), (False, False, 4))

    def test_timeout_boundary_not_greater_or_equal(self):
        controller = Controller()
        controller.receive(encode_vehicle(0, 20, True))
        controller.receive(encode_doors(0, 1))
        for timestamp in range(0, 310, 10):
            snapshot = controller.tick(timestamp)
        self.assertEqual(snapshot.timestamp_ms, 300)
        self.assertEqual(state(snapshot), (True, False, 6))
        failed = controller.tick(310)
        self.assertEqual(state(failed), (False, True, 1))
        self.assertIsNone(failed.pending_since_ms)

    def test_invalid_frame_does_not_reuse_previous_fresh_payload(self):
        controller = Controller()
        controller.receive(encode_vehicle(0, 20, True))
        controller.receive(encode_doors(0, 1))
        for timestamp in range(0, 210, 10):
            controller.tick(timestamp)
        controller.receive(Frame(210, 0x100, bytes.fromhex("d007020000000000")))
        self.assertEqual(state(controller.tick(210)), (False, True, 1))
        controller.receive(encode_doors(220, 1))  # Other stream cannot repair vehicle.
        self.assertEqual(state(controller.tick(220)), (False, True, 1))
        controller.receive(encode_vehicle(230, 20, True))
        recovered = controller.tick(230)
        self.assertEqual(state(recovered), (False, False, 5))
        self.assertEqual(recovered.pending_since_ms, 230)

    def test_receive_and_tick_share_monotonic_clock(self):
        cases = (
            (lambda c: c.tick(10), lambda c: c.tick(0)),
            (lambda c: c.receive(encode_doors(10, 1)), lambda c: c.receive(encode_doors(0, 1))),
            (lambda c: c.tick(10), lambda c: c.receive(encode_doors(0, 1))),
            (lambda c: c.receive(encode_doors(10, 1)), lambda c: c.tick(0)),
        )
        for number, (first, backwards) in enumerate(cases):
            with self.subTest(case=number):
                controller = Controller()
                first(controller)
                with self.assertRaises(ValueError):
                    backwards(controller)

    def test_equal_timestamps_are_allowed_and_last_input_wins(self):
        controller = Controller()
        controller.receive(encode_vehicle(0, 20, False))
        controller.receive(encode_vehicle(0, 20, True))
        controller.receive(encode_doors(0, 0))
        controller.receive(encode_doors(0, 1))
        self.assertEqual(state(controller.tick(0)), (False, False, 5))

    def test_unknown_frame_does_not_create_missing_inputs(self):
        controller = Controller()
        controller.receive(Frame(0, 0x555, b"\xff"))
        self.assertEqual(state(controller.tick(0)), (False, True, 1))


if __name__ == "__main__":
    unittest.main()
