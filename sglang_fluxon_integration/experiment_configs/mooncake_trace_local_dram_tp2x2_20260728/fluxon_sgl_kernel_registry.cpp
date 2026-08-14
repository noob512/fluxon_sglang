#include <ATen/ATen.h>
#include <c10/core/DispatchKey.h>
#include <torch/library.h>

#include <cstdint>

void write_mha_pages_to_fluxon_values(
    int64_t plan_ptr,
    const at::Tensor& page_indices,
    const at::Tensor& k_layer_ptrs,
    const at::Tensor& v_layer_ptrs,
    int64_t k_page_bytes,
    int64_t v_page_bytes,
    int64_t device_id);

void restore_mha_pages_from_fluxon_values(
    int64_t plan_ptr,
    const at::Tensor& page_indices,
    const at::Tensor& k_layer_ptrs,
    const at::Tensor& v_layer_ptrs,
    int64_t k_page_bytes,
    int64_t v_page_bytes,
    int64_t device_id);

void write_mla_pages_to_fluxon_values(
    int64_t plan_ptr,
    const at::Tensor& page_indices,
    const at::Tensor& layer_ptrs,
    int64_t page_bytes,
    int64_t device_id);

void restore_mla_pages_from_fluxon_values(
    int64_t plan_ptr,
    const at::Tensor& page_indices,
    const at::Tensor& layer_ptrs,
    int64_t page_bytes,
    int64_t device_id);

void write_mamba_state_to_fluxon_values(
    int64_t plan_ptr,
    int64_t slot_index,
    const at::Tensor& state_layer_ptrs,
    const at::Tensor& state_item_bytes,
    int64_t layer_num,
    int64_t device_id);

void restore_mamba_state_from_fluxon_values(
    int64_t plan_ptr,
    int64_t slot_index,
    const at::Tensor& state_layer_ptrs,
    const at::Tensor& state_item_bytes,
    int64_t layer_num,
    int64_t device_id);

TORCH_LIBRARY_FRAGMENT(sgl_kernel, m) {
  m.def(
      "write_mha_pages_to_fluxon_values(int plan_ptr, Tensor page_indices, Tensor k_layer_ptrs, "
      "Tensor v_layer_ptrs, int k_page_bytes, int v_page_bytes, int device_id) -> ()");
  m.impl("write_mha_pages_to_fluxon_values", c10::DispatchKey::CUDA, &write_mha_pages_to_fluxon_values);

  m.def(
      "restore_mha_pages_from_fluxon_values(int plan_ptr, Tensor page_indices, Tensor k_layer_ptrs, "
      "Tensor v_layer_ptrs, int k_page_bytes, int v_page_bytes, int device_id) -> ()");
  m.impl("restore_mha_pages_from_fluxon_values", c10::DispatchKey::CUDA, &restore_mha_pages_from_fluxon_values);

  m.def(
      "write_mla_pages_to_fluxon_values(int plan_ptr, Tensor page_indices, Tensor layer_ptrs, "
      "int page_bytes, int device_id) -> ()");
  m.impl("write_mla_pages_to_fluxon_values", c10::DispatchKey::CUDA, &write_mla_pages_to_fluxon_values);

  m.def(
      "restore_mla_pages_from_fluxon_values(int plan_ptr, Tensor page_indices, Tensor layer_ptrs, "
      "int page_bytes, int device_id) -> ()");
  m.impl("restore_mla_pages_from_fluxon_values", c10::DispatchKey::CUDA, &restore_mla_pages_from_fluxon_values);

  m.def(
      "write_mamba_state_to_fluxon_values(int plan_ptr, int slot_index, Tensor state_layer_ptrs, "
      "Tensor state_item_bytes, int layer_num, int device_id) -> ()");
  m.impl("write_mamba_state_to_fluxon_values", c10::DispatchKey::CUDA, &write_mamba_state_to_fluxon_values);

  m.def(
      "restore_mamba_state_from_fluxon_values(int plan_ptr, int slot_index, Tensor state_layer_ptrs, "
      "Tensor state_item_bytes, int layer_num, int device_id) -> ()");
  m.impl("restore_mamba_state_from_fluxon_values", c10::DispatchKey::CUDA, &restore_mamba_state_from_fluxon_values);
}
