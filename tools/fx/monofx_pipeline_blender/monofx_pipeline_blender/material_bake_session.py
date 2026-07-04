"""
Incremental material bake session for modal progress UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

import bpy

from .material_bake_targets import MaterialBakeRestoreRecord
from .material_bake import (
    BAKE_PASS_SPECS,
    BakePassSpec,
    BakeTarget,
    MaterialBakeResult,
    _active_uv_name,
    _apply_bake_margin,
    _bake_diffuse_zero_margin,
    _bake_without_shader_alpha,
    _cleanup_bake_prep_on_mesh,
    _enabled_pass_specs,
    _ensure_image,
    _finalize_baked_image,
    _film_transparent,
    _mesh_has_uv,
    _mesh_material_slot,
    _restore_bake_margin,
    _run_object_bake,
    _select_mesh_for_bake,
    _set_image_colorspace,
    _snapshot_bake_margin,
    _sync_view_layer,
    _activate_bake_targets_on_mesh,
    collect_bake_targets,
    resolve_shader_name,
    resolve_texture_stem,
    simplify_material_for_usd,
    texture_filename,
)


def tag_redraw_ui() -> None:
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


@dataclass
class _TargetState:
    target: BakeTarget
    mesh: bpy.types.Object
    work_mat: bpy.types.Material
    texture_stem: str
    uv_name: str
    source_material_name: str
    restore_slot_index: int = -1
    material_was_copied: bool = False
    baked_images: dict[str, bpy.types.Image] = field(default_factory=dict)
    texture_paths: dict[str, Path] = field(default_factory=dict)
    pass_index: int = 0


class MaterialBakeSession:
    """Run one bake pass per ``step()`` call so the UI can refresh."""

    def __init__(
        self,
        context: bpy.types.Context,
        meshes: Sequence[bpy.types.Object],
        *,
        scope: str = config.DEFAULT_MATERIAL_BAKE_SCOPE,
        material_prefix: str = config.DEFAULT_MATERIAL_PREFIX,
        targets: Optional[Sequence[BakeTarget]] = None,
        pass_base_color: bool = True,
        pass_roughness: bool = True,
        pass_normal: bool = True,
        pass_ao: bool = False,
        pass_opacity: bool = False,
        resolution: int = 2048,
        output_dir: Path,
        image_format: str = config.DEFAULT_MATERIAL_BAKE_IMAGE_FORMAT,
        uv_map_name: str = "",
        margin: int = config.DEFAULT_MATERIAL_BAKE_MARGIN,
        pack_images: bool = config.DEFAULT_MATERIAL_BAKE_PACK_IMAGES,
        simplify_shader: bool = config.DEFAULT_MATERIAL_BAKE_SIMPLIFY_SHADER,
        texture_stem_mode: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_MODE,
        shader_name_mode: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_MODE,
        texture_stem_template: str = config.DEFAULT_MATERIAL_BAKE_TEXTURE_STEM_TEMPLATE,
        shader_name_template: str = config.DEFAULT_MATERIAL_BAKE_SHADER_NAME_TEMPLATE,
    ) -> None:
        self.context = context
        self.meshes = meshes
        self.scope = scope
        self.material_prefix = material_prefix
        self.targets = targets
        self.pass_base_color = pass_base_color
        self.pass_roughness = pass_roughness
        self.pass_normal = pass_normal
        self.pass_ao = pass_ao
        self.pass_opacity = pass_opacity
        self.resolution = resolution
        self.output_dir = output_dir
        self.image_format = image_format
        self.uv_map_name = uv_map_name
        self.margin = margin
        self.pack_images = pack_images
        self.simplify_shader = simplify_shader
        self.texture_stem_mode = texture_stem_mode
        self.shader_name_mode = shader_name_mode
        self.texture_stem_template = texture_stem_template
        self.shader_name_template = shader_name_template

        self.result = MaterialBakeResult()
        self.passes: list[BakePassSpec] = []
        self.wants_opacity = False
        self.bake_targets: list[BakeTarget] = []
        self.target_index = 0
        self.target_state: Optional[_TargetState] = None
        self._pending_opacity = False
        self._scene_ready = False
        self._finished = False
        self.current_step = 0
        self.total_steps = 0
        self.restore_records: list[MaterialBakeRestoreRecord] = []

        self._prev_engine = ""
        self._prev_margin: object = None
        self._prev_active: Optional[bpy.types.Object] = None
        self._prev_selected: list[bpy.types.Object] = []

    @property
    def done(self) -> bool:
        return self._finished

    @property
    def status_label(self) -> str:
        if self._finished:
            return ""
        if not self._scene_ready:
            return "Preparing bake…"
        state = self.target_state
        if state is None:
            if self.target_index < len(self.bake_targets):
                return f"Target {self.target_index + 1}/{len(self.bake_targets)}"
            return "Finishing…"
        if self._pending_opacity:
            return f"{state.mesh.name} · Opacity"
        if state.pass_index < len(self.passes):
            spec = self.passes[state.pass_index]
            return f"{state.mesh.name} · {spec.slot_name}"
        return f"{state.mesh.name} · finalize"

    def begin(self) -> Optional[str]:
        self.passes = _enabled_pass_specs(
            pass_base_color=self.pass_base_color,
            pass_roughness=self.pass_roughness,
            pass_normal=self.pass_normal,
            pass_ao=self.pass_ao,
            pass_opacity=self.pass_opacity,
        )
        if not self.passes:
            return "Enable at least one bake pass."
        if self.pass_opacity and not self.pass_base_color:
            self.result.warnings.append(
                "Opacity requires Base Color bake (second diffuse pass)."
            )

        if self.targets is not None:
            self.bake_targets = [t for t in self.targets if t is not None]
        else:
            self.bake_targets = collect_bake_targets(
                self.meshes,
                scope=self.scope,
                material_prefix=self.material_prefix,
            )
        if not self.bake_targets:
            return "No mesh materials to bake."

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"Cannot create output folder: {exc}"

        self.result.output_dir = str(self.output_dir)
        self.wants_opacity = bool(self.pass_opacity)
        opacity_extra = (
            len(self.bake_targets)
            if self.wants_opacity and self.pass_base_color
            else 0
        )
        self.total_steps = len(self.bake_targets) * len(self.passes) + opacity_extra
        self._prepare_scene()
        return None

    def step(self) -> Optional[str]:
        if self._finished:
            return None

        if self.target_state is None:
            if self.target_index >= len(self.bake_targets):
                self._finish_result()
                return None
            err = self._init_target()
            if err:
                return err
            return None

        if self._pending_opacity:
            return self._run_opacity_pass()

        if self.target_state.pass_index < len(self.passes):
            return self._run_pass()

        return self._finalize_target()

    def finish(self) -> MaterialBakeResult:
        self._restore_scene()
        return self.result

    def _prepare_scene(self) -> None:
        scene = self.context.scene
        view_layer = self.context.view_layer
        self._prev_engine = scene.render.engine
        self._prev_margin = _snapshot_bake_margin(scene)
        self._prev_active = view_layer.objects.active
        self._prev_selected = list(self.context.selected_objects or [])
        scene.render.engine = "CYCLES"
        _apply_bake_margin(scene, self.margin)
        self._scene_ready = True

    def _restore_scene(self) -> None:
        if not self._scene_ready:
            return
        scene = self.context.scene
        view_layer = self.context.view_layer
        scene.render.engine = self._prev_engine
        _restore_bake_margin(scene, self._prev_margin)
        try:
            for obj in view_layer.objects:
                obj.select_set(False)
            for obj in self._prev_selected:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if self._prev_active and self._prev_active.name in bpy.data.objects:
                view_layer.objects.active = self._prev_active
        except Exception:
            pass
        self._scene_ready = False

    def _init_target(self) -> Optional[str]:
        while self.target_index < len(self.bake_targets):
            target = self.bake_targets[self.target_index]
            mesh = target.meshes[0]
            work_mat = target.material
            texture_stem = resolve_texture_stem(
                target.material.name,
                mesh.name,
                mode=self.texture_stem_mode,
                material_prefix=self.material_prefix,
                custom_template=self.texture_stem_template,
            )
            shader_name = resolve_shader_name(
                target.material.name,
                mesh.name,
                texture_stem,
                mode=self.shader_name_mode,
                material_prefix=self.material_prefix,
                custom_template=self.shader_name_template,
            )
            source_material_name = target.material.name
            restore_slot_index = -1
            material_was_copied = False
            if (self.scope or "").upper() == "PER_MESH":
                slot_idx = _mesh_material_slot(mesh, work_mat)
                if slot_idx is not None:
                    work_mat = work_mat.copy()
                    work_mat.name = shader_name
                    mesh.material_slots[slot_idx].material = work_mat
                    restore_slot_index = slot_idx
                    material_was_copied = True

            if not _mesh_has_uv(mesh, self.uv_map_name):
                self.result.warnings.append(f"{mesh.name}: missing UV map.")
                self.target_index += 1
                continue
            if _mesh_material_slot(mesh, work_mat) is None:
                self.result.warnings.append(
                    f"{mesh.name}: material '{work_mat.name}' not assigned."
                )
                self.target_index += 1
                continue

            self.target_state = _TargetState(
                target=target,
                mesh=mesh,
                work_mat=work_mat,
                texture_stem=texture_stem,
                uv_name=_active_uv_name(mesh, self.uv_map_name),
                source_material_name=source_material_name,
                restore_slot_index=restore_slot_index,
                material_was_copied=material_was_copied,
            )
            return None

        self._finish_result()
        return None

    def _run_pass(self) -> Optional[str]:
        state = self.target_state
        if state is None:
            return None
        spec = self.passes[state.pass_index]
        context = self.context
        scene = context.scene

        filename = texture_filename(
            state.texture_stem,
            spec.slot_name,
            image_format=self.image_format,
        )
        filepath = self.output_dir / filename
        image_name = f"mono_fx_bake_{state.work_mat.name}_{spec.slot_name}"
        image = _ensure_image(
            image_name=image_name,
            filepath=filepath,
            resolution=self.resolution,
            image_format=self.image_format,
        )
        if spec.non_color:
            _set_image_colorspace(image, "Non-Color")
        elif spec.key == "base_color":
            _set_image_colorspace(image, "sRGB")

        _sync_view_layer(context)
        try:
            _activate_bake_targets_on_mesh(
                state.mesh,
                state.work_mat,
                target_image=image,
                uv_map_name=state.uv_name,
            )
            _select_mesh_for_bake(context, state.mesh, state.work_mat)
            _sync_view_layer(context)
            with _film_transparent(scene, False):
                with _bake_without_shader_alpha(state.work_mat):
                    _run_object_bake(
                        spec,
                        scene,
                        bake_mat=state.work_mat,
                        bake_mesh=state.mesh,
                        target_image=image,
                    )
            _cleanup_bake_prep_on_mesh(state.mesh)
            if spec.key == "base_color" and self.wants_opacity:
                self._pending_opacity = True
            else:
                state.pass_index += 1
            _finalize_baked_image(image)
            state.baked_images[spec.slot_name] = image
            state.texture_paths[spec.slot_name] = filepath
            self.result.baked_passes += 1
        except Exception as exc:
            self.result.warnings.append(
                f"{state.work_mat.name}/{spec.slot_name}: bake failed ({exc})."
            )
            state.pass_index += 1
        finally:
            _cleanup_bake_prep_on_mesh(state.mesh)

        self.current_step += 1
        return None

    def _run_opacity_pass(self) -> Optional[str]:
        state = self.target_state
        if state is None:
            return None
        self._pending_opacity = False
        opacity_spec = BAKE_PASS_SPECS["opacity"]
        context = self.context
        scene = context.scene

        opacity_filename = texture_filename(
            state.texture_stem,
            opacity_spec.slot_name,
            image_format=self.image_format,
        )
        opacity_filepath = self.output_dir / opacity_filename
        opacity_image_name = (
            f"mono_fx_bake_{state.work_mat.name}_{opacity_spec.slot_name}"
        )
        opacity_image = _ensure_image(
            image_name=opacity_image_name,
            filepath=opacity_filepath,
            resolution=self.resolution,
            image_format=self.image_format,
            with_alpha=True,
        )
        _set_image_colorspace(opacity_image, "sRGB")
        try:
            _bake_diffuse_zero_margin(
                context,
                state.mesh,
                state.work_mat,
                scene,
                opacity_spec,
                target_image=opacity_image,
                uv_map_name=state.uv_name,
            )
            _finalize_baked_image(opacity_image)
            state.baked_images[opacity_spec.slot_name] = opacity_image
            state.texture_paths[opacity_spec.slot_name] = opacity_filepath
            self.result.baked_passes += 1
        except Exception as exc:
            self.result.warnings.append(
                f"{state.work_mat.name}/{opacity_spec.slot_name}: "
                f"bake failed ({exc})."
            )
        finally:
            _cleanup_bake_prep_on_mesh(state.mesh)

        state.pass_index += 1
        self.current_step += 1
        return None

    def _finalize_target(self) -> Optional[str]:
        state = self.target_state
        if state is None:
            return None
        if state.baked_images and self.simplify_shader:
            simplify_material_for_usd(
                state.work_mat,
                state.baked_images,
                uv_map_name=state.uv_name,
                texture_paths=state.texture_paths,
            )
        if self.pack_images:
            for baked in state.baked_images.values():
                try:
                    baked.pack()
                except Exception:
                    pass
        if state.baked_images:
            self.result.baked_targets += 1
            if state.material_was_copied and state.restore_slot_index >= 0:
                self.restore_records.append(
                    MaterialBakeRestoreRecord(
                        mesh_name=state.mesh.name,
                        slot_index=state.restore_slot_index,
                        source_material_name=state.source_material_name,
                        baked_material_name=state.work_mat.name,
                    )
                )

        self.target_state = None
        self.target_index += 1
        return None

    def _finish_result(self) -> None:
        self.result.ok = self.result.baked_targets > 0
        if not self.result.ok and not self.result.error:
            self.result.error = (
                "No materials were baked. Check UVs and material assignments."
            )
        self._finished = True


def run_material_bake_session(
    session: MaterialBakeSession,
    *,
    on_progress: Optional[Callable[[MaterialBakeSession], None]] = None,
) -> MaterialBakeResult:
    while not session.done:
        err = session.step()
        if err:
            session.result.error = err
            break
        if on_progress is not None:
            on_progress(session)
    return session.finish()
