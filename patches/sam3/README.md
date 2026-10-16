# SAM 3.1 compatibility patches

Pinned official source: `7f473cfd983d5eb43040ff608f66bff0d7bdcb53`.
Apply with `.runtime/bin/python scripts/apply_sam_patches.py`; repeated runs are safe.
The script rejects another source revision or conflicting edits rather than overwriting them.
Upstream license/attribution is retained in the submodule and `licenses/`.

1. `0001-session-init-option.patch`: the common session handler passed an unsupported
   `offload_state_to_cpu=False` to the multiplex model. Omit only the unsupported
   false default; reject an explicitly requested unsupported true value. No tensor
   calculations or learned parameters change.
2. `0002-first-point-output.patch`: the tracker produced a genuine first-click mask,
   but the cache merge discarded it when no detector result had yet been cached.
   Merge newly refined masks into an empty cache while retaining other objects.
   No synthetic masks or alternate model are introduced.
3. `0003-anchor-numpy-metadata.patch`: lower declared NumPy minimum from1.26 to1.24.4
   after genuine positive/negative,3-frame propagation, registered16-view propagation,
   native Object-Aware backward and original training passed on the anchor runtime.
   This validates these inference paths, not all upstream training/text features.

Runtime: Python3.10 / Torch2.5.1+cu118 / torchvision0.20.1 / NumPy1.24.4.
Use official `use_fa3=False`, `use_rope_real=False`, `compile=False`, `warm_up=False`.
Point-only propagation sends the explicitly known `start_frame_index`; otherwise
upstream's default searches detector outputs and reports no prompts.
Full final checkpoint key and shape equality is required before inference.

See `docs/STATUS.md`, `studio/tests/test_sam_compat.py`, and real ignored logs under
`evidence/sam31-smoke*` for reproductions and regression evidence. The scientific
Object-Aware files and native extension sources remain unchanged.
