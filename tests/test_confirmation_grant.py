from copy import deepcopy
import unittest

from components.confirmation_grant import grant_id, state_version


class ConfirmationGrantTests(unittest.TestCase):
    def snapshot(self):
        return {
            "identity": {"mode": "ROBOTAXI_RIDE", "user_id": "test"},
            "vehicle_state": {
                "speed_kmh": 72.1,
                "soc_percent": 80.0,
                "range_km": 350.0,
                "driving_hours": 0.0,
            },
            "order_state": {
                "passenger_coordinates": {"lat": 30.1, "lng": 120.1},
                "vehicle_coordinates": {"lat": 30.1001, "lng": 120.1001},
            },
            "environment_state": {"parking_policy": "允许临停"},
            "sensor_state": {
                "captured_at": "2026-09-03T01:00:00Z",
                "streams": [
                    {"id": "gnss_order", "readings": {"distance_m": 15}},
                    {
                        "id": "vehicle_telemetry",
                        "readings": {
                            "speed_kmh": 72.1,
                            "soc_percent": 80.0,
                            "range_km": 350.0,
                            "driving_hours": 0.0,
                        },
                    },
                ],
            },
        }

    def test_sensor_timestamp_does_not_invalidate_confirmation(self):
        first = self.snapshot()
        second = deepcopy(first)
        second["sensor_state"]["captured_at"] = "2026-09-03T01:00:01Z"
        self.assertEqual(state_version(first), state_version(second))
        self.assertEqual(
            grant_id("contact_vehicle", {"action": "both"}, first),
            grant_id("contact_vehicle", {"action": "both"}, second),
        )

    def test_derived_cabin_readback_does_not_invalidate_confirmation(self):
        first = self.snapshot()
        first["sensor_state"]["streams"].append(
            {
                "id": "cabin_environment",
                "readings": {"cabin_temperature_c": 24},
            }
        )
        second = deepcopy(first)
        second["sensor_state"]["streams"][-1]["readings"][
            "cabin_temperature_c"
        ] = 21
        self.assertEqual(state_version(first), state_version(second))
        self.assertEqual(
            grant_id("plan_route", {"destination": "最近安全服务区"}, first),
            grant_id("plan_route", {"destination": "最近安全服务区"}, second),
        )

    def test_route_confirmation_tolerates_natural_speed_bucket_crossing(self):
        first = self.snapshot()
        first["vehicle_state"]["speed_kmh"] = 94.6
        second = deepcopy(first)
        second["vehicle_state"]["speed_kmh"] = 96.0
        self.assertNotEqual(state_version(first), state_version(second))
        self.assertEqual(
            grant_id("plan_route", {"destination": "最近安全服务区"}, first),
            grant_id("plan_route", {"destination": "最近安全服务区"}, second),
        )

    def test_safety_state_change_invalidates_confirmation(self):
        first = self.snapshot()
        second = deepcopy(first)
        second["order_state"]["vehicle_coordinates"]["lat"] = 30.2
        self.assertNotEqual(state_version(first), state_version(second))

    def test_small_telemetry_drift_keeps_same_safety_bucket(self):
        first = self.snapshot()
        second = deepcopy(first)
        second["vehicle_state"].update(
            {
                "speed_kmh": 73.4,
                "soc_percent": 80.4,
                "range_km": 350.8,
                "driving_hours": 0.02,
            }
        )
        second["sensor_state"]["streams"][1]["readings"].update(
            {
                "speed_kmh": 73.4,
                "soc_percent": 80.4,
                "range_km": 350.8,
                "driving_hours": 0.02,
            }
        )
        self.assertEqual(state_version(first), state_version(second))

    def test_material_telemetry_change_invalidates_confirmation(self):
        first = self.snapshot()
        second = deepcopy(first)
        second["vehicle_state"]["speed_kmh"] = 81
        self.assertNotEqual(state_version(first), state_version(second))


if __name__ == "__main__":
    unittest.main()
