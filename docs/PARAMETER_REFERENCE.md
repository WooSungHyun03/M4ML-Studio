# Supported task parameters

Generated from the actual Provider schema in `studio/task_settings.py`. Bounds are input/resource limits, not optimal scientific ranges. All processing values apply to the next run and require rerunning that stage; changing TSDF settings requires only re-extraction. Review/view values are project display overrides. No runtime optimizer mutation is supported.

## camera / colmap

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `max_image_size` / `FeatureExtraction.max_image_size` | `-1` | integer / -1…8192 | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | -1: 엔진 기본값, 양수: 긴 변의 최대 픽셀 수. |
| `matching` / `matching` | `exhaustive` | choice / ['exhaustive', 'sequential'] | studio/providers/camera_colmap.py | 전체 쌍 / 촬영 순서. 순차 매칭은 순서가 있는 사진에 사용하세요. |
| `use_gpu` / `use_gpu` | `True` | boolean / true / false | studio/engines.py | 특징점 추출·매칭에 적용. 카메라 자세 추정은 CPU에서 실행합니다. |
| `camera_model` / `ImageReader.camera_model` | `SIMPLE_RADIAL` | choice / ['SIMPLE_RADIAL', 'RADIAL', 'OPENCV', 'PINHOLE', 'SIMPLE_PINHOLE'] | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 카메라 모델 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `single_camera` / `ImageReader.single_camera` | `False` | boolean / true / false | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 하나의 카메라 공유 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `max_features` / `SiftExtraction.max_num_features` | `8192` | integer / 512…65536 | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 최대 특징점 수 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `matching_error` / `TwoViewGeometry.max_error` | `4.0` | number / 0.1…32 | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 매칭 기하 오차 한계 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `minimum_matches` / `Mapper.min_num_matches` | `15` | integer / 8…100 | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 최소 매칭 수 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `refine_focal` / `Mapper.ba_refine_focal_length` | `True` | boolean / true / false | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 초점 거리 보정 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `refine_principal` / `Mapper.ba_refine_principal_point` | `False` | boolean / true / false | COLMAP4.2.1 feature_extractor / exhaustive_matcher / mapper -h | 주점 보정 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `threads` / `threads` | `16` | integer / 1…64 | studio/providers/camera_colmap.py | CPU 스레드 값을 변경합니다. 실행 결과에 영향을 줍니다. |

Application: 다음 실행부터 적용 · 실행 중에는 변경할 수 없습니다. 기존 결과는 보존합니다.
GPU/VRAM: Resolution/count/densification and extraction limits can increase GPU/CPU memory, runtime and disk. Camera Mapper/BA is CPU; feature extraction/matching use the selected GPU. Mesh lighting and point size affect its viewport only.

## segmentation / sam31

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `propagation_radius` / `propagation_radius` | `2` | integer / 1…25 | studio/sam31.py radius; MaskStage.tsx | 주변만 다시 전파할 때 앞뒤 사진 수입니다. 전체 전파에는 적용하지 않습니다. |
| `fill_hole_area` / `fill_hole_area` | `0` | integer / 0…4096 | vendor/sam3/sam3/model_builder.py:1183; sam3_multiplex_tracking.py:2936 | 공식 모델의 후처리 면적 기준(픽셀). 0은 사용 안 함. 다음 클릭·전파부터 적용합니다. |
| `sprinkle_removal_area` / `sprinkle_removal_area` | `0` | integer / 0…4096 | vendor/sam3/sam3/model_builder.py:1183; sam3_multiplex_tracking.py:2936 | 공식 모델의 작은 연결 영역 제거 기준(픽셀). 0은 사용 안 함. |
| `coverage_warning` / `coverage_warning` | `0.98` | number / 0.5…1 | studio/sam31.py | 사진에서 마스크가 차지하는 비율. 모델 신뢰도가 아닌 검토용 경고 기준입니다. |
| `offload_video_to_cpu` / `offload_video_to_cpu` | `True` | boolean / true / false | studio/sam31.py; sam31_session.py | GPU 메모리를 절약합니다. 현재 세션의 다음 사진 준비·전파부터 적용합니다. |

Application: 다음 실행부터 적용 · 실행 중에는 변경할 수 없습니다. 기존 결과는 보존합니다.
GPU/VRAM: Resolution/count/densification and extraction limits can increase GPU/CPU memory, runtime and disk. Camera Mapper/BA is CPU; feature extraction/matching use the selected GPU. Mesh lighting and point size affect its viewport only.

## review / studio_review

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `review_filter` / `review_filter` | `all` | choice / ['all', 'unreviewed', 'warnings', 'reviewed'] | frontend/src/stages/MaskStage.tsx | 오른쪽 사진 목록을 필터링합니다. 현재 사진과 이전·다음 이동 순서는 유지합니다. |
| `overlay_opacity` / `overlay_opacity` | `0.4` | number / 0…1 | frontend/src/MaskEditor.tsx | 마스크 투명도 값을 변경합니다. 표시에만 적용합니다. |
| `overlay_color` / `overlay_color` | `#f0a53a` | color / #RRGGBB | frontend/src/MaskEditor.tsx | 마스크 색상 값을 변경합니다. 표시에만 적용합니다. |
| `show_boundary` / `show_boundary` | `False` | boolean / true / false | frontend/src/MaskEditor.tsx | 경계 표시 값을 변경합니다. 표시에만 적용합니다. |
| `mask_only` / `mask_only` | `False` | boolean / true / false | frontend/src/MaskEditor.tsx | 마스크만 보기 값을 변경합니다. 표시에만 적용합니다. |
| `auto_next` / `auto_next` | `False` | boolean / true / false | frontend/src/stages/MaskStage.tsx | 저장 후 다음 사진 값을 변경합니다. 표시에만 적용합니다. |
| `warnings_first` / `warnings_first` | `False` | boolean / true / false | frontend/src/stages/MaskStage.tsx | 경고 사진 우선 값을 변경합니다. 표시에만 적용합니다. |
| `brush_size` / `brush_size` | `18` | integer / 2…100 | frontend/src/MaskEditor.tsx | 브러시 크기 값을 변경합니다. 표시에만 적용합니다. |

Application: 즉시 표시 적용 · 원본 파일은 변경하지 않습니다.
GPU/VRAM: Mask display and list preferences do not change inference/training.

## training / object_aware_2dgs

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `iterations` / `iterations` | `30000` | integer / 100…100000 | arguments/__init__.py; train.py | 학습 횟수 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `image_resolution` / `resolution` | `-1` | integer / -1…8192 | arguments/__init__.py; train.py | -1: 원본 코드의 자동 해상도. 1·2·4·8: 축소 배율, 그 외 양수: 가로 픽셀 수. |
| `checkpoint_every` / `checkpoint_every` | `2500` | integer / 10…50000 | studio/providers/training_object_aware.py | 반복 횟수 단위. 마지막 반복도 저장합니다. |
| `alpha_weight` / `lambda_pa` | `0.1` | number / 0…10 | arguments/__init__.py; train.py | 알파 Polarization 가중치 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `object_weight` / `lambda_po` | `1.0` | number / 0…10 | arguments/__init__.py; train.py | 객체 Polarization 가중치 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `normal_weight` / `lambda_normal` | `0.05` | number / 0…10 | arguments/__init__.py; train.py | 원본 코드에서 7,000회 이후 적용합니다. |
| `distortion_weight` / `lambda_dist` | `0.0` | number / 0…100 | arguments/__init__.py; train.py | 원본 코드에서 3,000회 이후 적용합니다. |
| `position_lr_initial` / `position_lr_init` | `0.00016` | number / 0…0.1 | arguments/__init__.py; train.py | 위치 초기 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `position_lr_final` / `position_lr_final` | `1.6e-06` | number / 0…0.1 | arguments/__init__.py; train.py | 위치 최종 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `feature_lr` / `feature_lr` | `0.0025` | number / 0…1 | arguments/__init__.py; train.py | 색상 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `opacity_lr` / `opacity_lr` | `0.05` | number / 0…1 | arguments/__init__.py; train.py | 불투명도 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `object_lr` / `objectmark_lr` | `0.01` | number / 0…1 | arguments/__init__.py; train.py | 객체 점수 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `scale_lr` / `scaling_lr` | `0.005` | number / 0…1 | arguments/__init__.py; train.py | 크기 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `rotation_lr` / `rotation_lr` | `0.001` | number / 0…1 | arguments/__init__.py; train.py | 회전 학습률 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `densify_threshold` / `densify_grad_threshold` | `0.0002` | number / 0…1 | arguments/__init__.py; train.py | 밀도 확장 기울기 기준 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `opacity_cull` / `opacity_cull` | `0.05` | number / 0…1 | arguments/__init__.py; train.py | 불투명도 제거 기준 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `object_prune_threshold` / `objectmark_prune_threshold` | `0.5` | number / 0…1 | arguments/__init__.py; train.py | 객체 점수 제거 기준 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `lr_schedule_steps` / `position_lr_max_steps` | `30000` | integer / 1…100000 | arguments/__init__.py; train.py | 위치 학습률 스케줄 길이 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `lr_delay` / `position_lr_delay_mult` | `0.01` | number / 0…1 | arguments/__init__.py; train.py | 위치 학습률 지연 배율 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `dense_fraction` / `percent_dense` | `0.01` | number / 1e-06…1 | arguments/__init__.py; train.py | 밀도 확장 크기 비율 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `densify_interval` / `densification_interval` | `100` | integer / 1…10000 | arguments/__init__.py; train.py | 밀도 확장 간격 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `densify_from` / `densify_from_iter` | `500` | integer / 0…100000 | arguments/__init__.py; train.py | 밀도 확장 시작 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `densify_until` / `densify_until_iter` | `15000` | integer / 1…100000 | arguments/__init__.py; train.py | 밀도 확장 종료 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `opacity_reset_interval` / `opacity_reset_interval` | `3000` | integer / 1…100000 | arguments/__init__.py; train.py | 불투명도 초기화 간격 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `object_prune_from` / `objectmark_prune_from_iter` | `2500` | integer / 0…100000 | arguments/__init__.py; train.py | 객체 제거 시작 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `object_prune_interval` / `objectmark_prune_interval` | `500` | integer / 1…100000 | arguments/__init__.py; train.py | 객체 제거 간격 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `sh_degree` / `sh_degree` | `3` | integer / 0…3 | arguments/__init__.py; train.py | SH 차수 값을 변경합니다. 실행 결과에 영향을 줍니다. |
| `white_background` / `white_background` | `False` | boolean / true / false | arguments/__init__.py; train.py | 흰색 학습 배경 값을 변경합니다. 실행 결과에 영향을 줍니다. |

Application: 다음 실행부터 적용 · 실행 중에는 변경할 수 없습니다. 기존 결과는 보존합니다.
GPU/VRAM: Resolution/count/densification and extraction limits can increase GPU/CPU memory, runtime and disk. Camera Mapper/BA is CPU; feature extraction/matching use the selected GPU. Mesh lighting and point size affect its viewport only.

## mesh / object_aware_tsdf

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `mesh_res` / `mesh_res` | `1024` | integer / 64…2048 | render.py:44 | TSDF 격자 해상도. 높이면 메모리·처리량이 증가합니다. 표시 해상도와 별개입니다. |
| `voxel_size` / `voxel_size` | `-1.0` | number / -1…10 | render.py:39 | -1: 장면 크기와 생성 해상도로 자동 계산. |
| `sdf_trunc` / `sdf_trunc` | `-1.0` | number / -1…100 | render.py:41 | -1: 원본 코드의 자동 계산. |
| `depth_trunc` / `depth_trunc` | `-1.0` | number / -1…10000 | render.py:40 | -1: 장면 크기에서 자동 계산. |
| `num_cluster` / `num_cluster` | `50` | integer / 1…1000 | render.py:42 | 원본 메시 후처리에서 큰 연결 요소를 보존합니다. |
| `unbounded` / `unbounded` | `False` | boolean / true / false | render.py:43 | 비한정 장면 추출 값을 변경합니다. 실행 결과에 영향을 줍니다. |

Application: 다음 실행부터 적용 · 실행 중에는 변경할 수 없습니다. 기존 결과는 보존합니다.
GPU/VRAM: Resolution/count/densification and extraction limits can increase GPU/CPU memory, runtime and disk. Camera Mapper/BA is CPU; feature extraction/matching use the selected GPU. Mesh lighting and point size affect its viewport only.

## view / studio_view

| ID / native variable | Default | Type / allowed | Source | Effect |
| --- | --- | --- | --- | --- |
| `render_scale` / `render_scale` | `1.0` | number / 0.25…2 | frontend/src/MeshViewer.tsx; GaussianViewer.tsx | 3D 렌더링 영역에만 적용합니다. UI 글자 크기는 유지합니다. |
| `background` / `background` | `#1c1c20` | color / #RRGGBB | frontend/src/MeshViewer.tsx | 뷰포트 배경 값을 변경합니다. 표시에만 적용합니다. |
| `grid` / `grid` | `True` | boolean / true / false | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 그리드 값을 변경합니다. 표시에만 적용합니다. |
| `axes` / `axes` | `False` | boolean / true / false | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 좌표축 값을 변경합니다. 표시에만 적용합니다. |
| `orthographic` / `orthographic` | `False` | boolean / true / false | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. Gaussian 원본 렌더러는 원근 투영만 지원합니다. |
| `rotate_speed` / `rotate_speed` | `1.0` | number / 0.1…5 | Three.js OrbitControls.rotateSpeed | 회전 감도 값을 변경합니다. 표시에만 적용합니다. |
| `zoom_speed` / `zoom_speed` | `1.0` | number / 0.1…5 | Three.js OrbitControls.zoomSpeed | 확대 감도 값을 변경합니다. 표시에만 적용합니다. |
| `pan_speed` / `pan_speed` | `1.0` | number / 0.1…5 | Three.js OrbitControls.panSpeed | 이동 감도 값을 변경합니다. 표시에만 적용합니다. |
| `light_azimuth` / `light_azimuth` | `-35.0` | number / -180…180 | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 주 조명 방향 값을 변경합니다. 표시에만 적용합니다. |
| `mesh_mode` / `mesh_mode` | `color` | choice / ['color', 'vertex', 'shaded', 'wire', 'normals', 'points'] | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 메시 표시 모드 값을 변경합니다. 표시에만 적용합니다. |
| `gaussian_mode` / `gaussian_mode` | `rgb` | choice / ['rgb', 'alpha', 'depth', 'normal', 'objectmark'] | studio/providers/render_gaussian_remote.py | Gaussian 표시 모드 값을 변경합니다. 표시에만 적용합니다. |
| `light` / `light` | `1.0` | number / 0…5 | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 메시의 셰이딩·정점 색상 모드에 적용합니다. 원본 색상 모드는 조명을 사용하지 않습니다. |
| `point_size` / `point_size` | `2.0` | number / 0.5…12 | frontend/src/MeshViewer.tsx | 메시 뷰어에 적용합니다. 포인트 크기 값을 변경합니다. 표시에만 적용합니다. |
| `fov` / `fov` | `35.0` | number / 15…100 | Three.js PerspectiveCamera | 시야각 값을 변경합니다. 표시에만 적용합니다. |
| `near` / `near` | `0.001` | number / 1e-05…10 | Three.js Camera.near; gaussian_protocol | 가까운 절단면 값을 변경합니다. 표시에만 적용합니다. |
| `far` / `far` | `100000.0` | number / 1…100000 | Three.js Camera.far; gaussian_protocol | 먼 절단면 값을 변경합니다. 표시에만 적용합니다. |
| `screenshot_scale` / `screenshot_scale` | `1.0` | number / 0.5…4 | frontend/src/MeshViewer.tsx | 스크린샷 배율 값을 변경합니다. 표시에만 적용합니다. |

Application: 즉시 표시 적용 · 원본 파일은 변경하지 않습니다.
GPU/VRAM: Resolution/count/densification and extraction limits can increase GPU/CPU memory, runtime and disk. Camera Mapper/BA is CPU; feature extraction/matching use the selected GPU. Mesh lighting and point size affect its viewport only.

## Intentionally internal / unsupported

- Masked L1 has its original fixed coefficient. `lambda_dssim` is declared upstream but unused by the actual training loop, so it is not exposed. Normal/distortion weights retain their original activation thresholds (7000/3000). Optimizer type and research formulas are unchanged.
- SAM point inference emits binary masks with its native0-logit threshold. No fabricated probability, sensitivity, confidence or stability slider is exposed. Official hole/sprinkle postprocessing is available and was tested on GPU. Coverage warnings measure area, not model confidence.
- Compilation/kernel/checkpoint architecture, camera/frame identity, model source paths, CUDA backend, original loss formulas and arbitrary command flags are internal. No generic “quality” slider silently substitutes another model.
- Arbitrary key remapping, Gaussian orthographic/grid/scene lighting, Gaussian point-size controls and non-native Gaussian conversion are not claimed. Existing viewer modes and fixed shortcuts remain available.
- Presets: camera 빠름=(1600,4096), 균형=(2400,8192), 높음=(-1,16384) for(max_image_size,max_features); training 빠름=3000, 균형=15000, 높음=30000 iterations. Other values stay visible; users can inspect/edit before saving. Short runs do not establish final quality.
