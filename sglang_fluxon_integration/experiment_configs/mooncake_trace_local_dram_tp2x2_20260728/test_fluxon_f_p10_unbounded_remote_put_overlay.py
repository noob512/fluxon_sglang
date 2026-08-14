from __future__ import annotations

import unittest

import derive_fluxon_f_p10_unbounded_remote_put_overlay as overlay


class FluxonFP10UnboundedRemotePutOverlayTests(unittest.TestCase):
    def test_removes_both_remote_put_admission_limits(self) -> None:
        source = (
            "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=17179869184\n"
            "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=4096\n"
            '  echo "pplx_rails local=2 remote=2 devices=mlx5_0,mlx5_1"\n'
        )
        derived = overlay.derive_wrapper(source)
        self.assertNotIn("OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES", derived)
        self.assertNotIn("OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS", derived)
        self.assertIn("remote_put_admission bytes=unbounded items=unbounded", derived)

    def test_preserves_unrelated_p9_configuration(self) -> None:
        source = (
            "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=17179869184\n"
            "  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=4096\n"
            "  SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA=1\n"
            "  SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT=1\n"
            '  echo "pplx_rails local=2 remote=2 devices=mlx5_0,mlx5_1"\n'
        )
        derived = overlay.derive_wrapper(source)
        self.assertIn("SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA=1", derived)
        self.assertIn("SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT=1", derived)
        self.assertIn("pplx_rails local=2 remote=2", derived)

    def test_changed_baseline_fails_exact_count_gate(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 1 occurrence"):
            overlay.derive_wrapper("unrelated launcher")


if __name__ == "__main__":
    unittest.main()
