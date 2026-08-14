from __future__ import annotations

import unittest

import derive_fluxon_f_two_rail_overlay as overlay


class FluxonFTwoRailOverlayTests(unittest.TestCase):
    def test_inner_removes_third_and_fourth_domains_from_both_configs(self) -> None:
        source = (
            "# Derived for Mooncake Conversation F: one 256-GiB owner, two TP2 "
            "external clients, four HCAs.\n"
            'RDMA_DEVICE_2="${FLUXON_EXTERNAL_RDMA_DEVICE_2:?missing '
            'FLUXON_EXTERNAL_RDMA_DEVICE_2}"\n'
            'RDMA_DEVICE_3="${FLUXON_EXTERNAL_RDMA_DEVICE_3:?missing '
            'FLUXON_EXTERNAL_RDMA_DEVICE_3}"\n'
            'owner:\n  - "${RDMA_DEVICE_0}"\n  - "${RDMA_DEVICE_1}"\n'
            '  - "${RDMA_DEVICE_2}"\n  - "${RDMA_DEVICE_3}"\n'
            'client:\n  - "${RDMA_DEVICE_0}"\n  - "${RDMA_DEVICE_1}"\n'
            '  - "${RDMA_DEVICE_2}"\n  - "${RDMA_DEVICE_3}"\n'
        )
        derived = overlay.derive_inner(source)
        self.assertIn("common two-rail PPLX", derived)
        self.assertNotIn("RDMA_DEVICE_2", derived)
        self.assertNotIn("RDMA_DEVICE_3", derived)
        self.assertEqual(derived.count('  - "${RDMA_DEVICE_0}"'), 2)
        self.assertEqual(derived.count('  - "${RDMA_DEVICE_1}"'), 2)

    def test_wrapper_gates_and_exports_only_two_domains(self) -> None:
        source = (
            "  for hca in mlx5_0 mlx5_1 mlx5_2 mlx5_3; do\n"
            "  FLUXON_EXTERNAL_RDMA_DEVICE_2=mlx5_2\n"
            "  FLUXON_EXTERNAL_RDMA_DEVICE_3=mlx5_3\n"
            '  echo "h2d_mode layer_batch_dma=$layer_batch_dma '
            'background_dma_submit=$background_dma_submit"\n'
        )
        derived = overlay.derive_wrapper(source)
        self.assertIn("for hca in mlx5_0 mlx5_1; do", derived)
        self.assertNotIn("FLUXON_EXTERNAL_RDMA_DEVICE_2", derived)
        self.assertNotIn("FLUXON_EXTERNAL_RDMA_DEVICE_3", derived)
        self.assertIn("pplx_rails local=2 remote=2", derived)

    def test_changed_baseline_fails_exact_count_gate(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected 1 occurrence"):
            overlay.derive_wrapper("unrelated launcher")

    def test_base_replayer_binds_two_rail_list_to_explicit_profile(self) -> None:
        source = (
            "LOCAL_TOTAL_BYTES = 274_877_906_944\nTCP_CONNECTOR_CONFIG = {\n"
            '        if local.get("rdma_hcas") != '
            '["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"]:\n'
            '            raise ValidationError("group F local HCA list mismatch")\n'
        )
        derived = overlay.derive_base_replayer(source)
        self.assertIn("FLUXON_F_COMMON_TWO_RAIL_HCAS", derived)
        self.assertIn('rdma_profile == "pplx_common_two_rail"', derived)
        self.assertIn("group F local HCA list/profile mismatch", derived)


if __name__ == "__main__":
    unittest.main()
