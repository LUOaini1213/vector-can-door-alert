"""Independent byte vectors: expected payloads are literal values, not round trips."""
import math
import unittest

from door_alert.protocol import (
    Frame, decode_alert, decode_doors, decode_vehicle,
    encode_alert, encode_doors, encode_vehicle,
)


class ProtocolVectors(unittest.TestCase):
    def test_vehicle_little_endian_and_scale_known_vectors(self):
        # 123.45 / 0.01 = 12345 = 0x3039, Intel bytes = 39 30.
        vectors = [
            (0.00, False, "0000000000000000", 0),
            (3.00, True, "2c01010000000000", 300),
            (4.99, True, "f301010000000000", 499),
            (5.00, True, "f401010000000000", 500),
            (123.45, True, "3930010000000000", 12345),
            (250.00, True, "a861010000000000", 25000),
        ]
        for speed, ignition, hex_data, speed_raw in vectors:
            with self.subTest(speed=speed):
                actual = encode_vehicle(120, speed, ignition)
                self.assertEqual(actual.arbitration_id, 0x100)
                self.assertEqual(actual.timestamp_ms, 120)
                self.assertEqual(actual.data, bytes.fromhex(hex_data))
                decoded = decode_vehicle(Frame(120, 0x100, bytes.fromhex(hex_data)))
                self.assertEqual(decoded, {"speed_raw": speed_raw, "ignition": ignition})

    def test_door_bit_positions_known_vectors(self):
        for mask in (0, 1, 2, 4, 8, 15):
            with self.subTest(mask=mask):
                expected = bytes([mask, 0, 0, 0, 0, 0, 0, 0])
                frame = encode_doors(10, mask)
                self.assertEqual(frame.arbitration_id, 0x101)
                self.assertEqual(frame.data, expected)
                self.assertEqual(decode_doors(Frame(10, 0x101, expected)), mask)

    def test_alert_known_vectors(self):
        for warning, fault, reason, payload in [
            (False, True, 1, "0001010000000000"),
            (False, False, 3, "0000030000000000"),
            (True, False, 6, "0100060000000000"),
        ]:
            with self.subTest(reason=reason):
                frame = encode_alert(200, warning, fault, reason)
                self.assertEqual(frame.arbitration_id, 0x200)
                self.assertEqual(frame.data, bytes.fromhex(payload))
                self.assertEqual(
                    decode_alert(Frame(200, 0x200, bytes.fromhex(payload))),
                    {"warning": warning, "data_fault": fault, "reason": reason},
                )

    def test_decoders_reject_dlc_0_3_7_9(self):
        for decoder, message_id in [
            (decode_vehicle, 0x100), (decode_doors, 0x101), (decode_alert, 0x200)
        ]:
            for length in (0, 3, 7, 9):
                with self.subTest(decoder=decoder.__name__, length=length):
                    with self.assertRaises(ValueError):
                        decoder(Frame(0, message_id, bytes(length)))

    def test_invalid_vehicle_physical_value_and_ignition(self):
        for payload in ("a961010000000000", "ffff010000000000", "e803020000000000"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                decode_vehicle(Frame(0, 0x100, bytes.fromhex(payload)))

    def test_invalid_door_high_bits(self):
        for mask in (16, 128, 255):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                decode_doors(Frame(0, 0x101, bytes([mask]) + bytes(7)))

    def test_encode_rejects_out_of_range_nonfinite_speeds(self):
        for speed in (-0.01, 250.01, math.nan, math.inf, -math.inf):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                encode_vehicle(0, speed, True)

    def test_encode_rejects_invalid_door_masks(self):
        for mask in (-1, 16, 255):
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                encode_doors(0, mask)


if __name__ == "__main__":
    unittest.main()
