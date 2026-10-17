# v1 internal candidate install/update/rollback

Supported validation target: Ubuntu24.04 x86_64/X11, RTX4080/driver580.173.02. A1.0 archive is source+staticUI+COLMAP/SIBR runtime; Python/Qt/CUDA11.8 native extensions are installed into a private runtime. Weights and NVIDIA driver are excluded. Follow README system dependencies and configure a legitimately obtained official SAM3.1 checkpoint. Public redistribution remains unapproved.

Verify the archive SHA, extract into a new folder, then run ./scripts/install.sh as an ordinary user. The installer verifies every manifest file including licenses/sbom.json, atomically installs into XDG_DATA_HOME/m4ml-studio/apps/1.0.0, keeps earlier app directories and uses the private shared compatibility runtime. No sudo/driver change. Launch via generated M4ML Studio desktop entry or python3 scripts/launch.py from the extracted folder.

Projects and masks are not copied over by app updates. SQLite/manifest schema remains compatible; per-project task settings migrate lazily and preserve legacy iterations until the training namespace is explicitly saved/reset. Existing settings schema upgrades have backup files; unknown future schemas fail rather than discard values. Old checkpoints without immutable settings/content identity are preserved but cannot be safely resumed automatically.

Stop active jobs normally before update/uninstall; do not run two API instances against one project store while training. Default desktop chooses a free loopback port. Uninstall removes the launcher/registry and retires its owned app; project data, runtime and previous installs stay. Reinstall the same candidate to reopen those projects. For rollback use the earlier version installer/launcher; if an older version cannot interpret a new setting, retain its original project backup and do not erase unfamiliar fields.

Exact non-root fresh-install,0.4→1.0 upgrade, lifecycle and content-hash results are recorded in V1_RELEASE_REPORT.md and evidence/v1/install/. No existing user installation is replaced by these tests.
