import unittest

from sam3.model.sam3_base_predictor import Sam3BasePredictor
from sam3.model.sam3_multiplex_tracking import Sam3MultiplexTracking


class Multiplex:
    def init_state(
        self, resource_path, offload_video_to_cpu=False, async_loading_frames=False
    ):
        return {"resource": resource_path, "video_offloaded": offload_video_to_cpu}


class Original:
    def init_state(
        self, resource_path, offload_video_to_cpu=False, offload_state_to_cpu=False
    ):
        return {"resource": resource_path, "state_offloaded": offload_state_to_cpu}


class SessionCompatibilityTests(unittest.TestCase):
    def predictor(self, model):
        predictor = Sam3BasePredictor()
        predictor.model = model
        return predictor

    def test_multiplex_session_default_and_video_offload(self):
        p = self.predictor(Multiplex())
        session = p.start_session("실제 프레임 경로", offload_video_to_cpu=True)
        self.assertEqual(
            p._all_inference_states[session["session_id"]]["state"],
            {"resource": "실제 프레임 경로", "video_offloaded": True},
        )

    def test_unsupported_state_offload_fails_explicitly(self):
        p = self.predictor(Multiplex())
        with self.assertRaisesRegex(ValueError, "offload_state_to_cpu"):
            p.start_session("frames", offload_state_to_cpu=True)
        self.assertEqual(p._all_inference_states, {})

    def test_original_state_offload_preserved(self):
        p = self.predictor(Original())
        session = p.start_session("frames", offload_state_to_cpu=True)
        self.assertTrue(
            p._all_inference_states[session["session_id"]]["state"]["state_offloaded"]
        )

    def test_first_point_without_detector_cache_keeps_real_mask(self):
        sentinel_mask = object()
        state = {"cached_frame_outputs": {}}
        result = Sam3MultiplexTracking._build_sam2_output(
            None, state, 0, {1: sentinel_mask}
        )
        self.assertIs(result[1], sentinel_mask)
        self.assertEqual(state["cached_frame_outputs"], {})

    def test_refinement_preserves_other_objects_and_cached_original(self):
        state = {"cached_frame_outputs": {0: {1: "old", 2: "approved"}}}
        result = Sam3MultiplexTracking._build_sam2_output(
            None, state, 0, {1: "refined"}
        )
        self.assertEqual(result, {1: "refined", 2: "approved"})
        self.assertEqual(state["cached_frame_outputs"][0][1], "old")
