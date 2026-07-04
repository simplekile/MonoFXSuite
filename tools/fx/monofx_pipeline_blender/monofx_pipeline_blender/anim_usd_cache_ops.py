"""

Anim USD cache export operator.

"""



from __future__ import annotations



import bpy

from pathlib import Path

from bpy.types import Context, Operator



from . import anim_usd_cache_asset_list as asset_list

from . import anim_usd_cache_paths_ui as path_ui

from .anim_usd_cache_exporter import (

    UsdAnimCacheExportSession,

    UsdAnimCacheMultiExportSession,

    check_pxr_available,

    collect_camera_collection_objects,

    collect_export_camera_objects,

    collect_export_mesh_objects,

    collect_publish_geo_mesh_objects,

    collect_selected_mesh_objects,

    format_export_elapsed,

    resolve_geo_job_mesh_objects,

)

from .anim_usd_export_planner import plan_geo_export_jobs




_ACTIVE_ANIM_USD_SESSION: UsdAnimCacheExportSession | UsdAnimCacheMultiExportSession | None = None




class MONOFX_OT_export_anim_usd_cache(Operator):

    bl_idname = "wm.mono_fx_export_anim_usd_cache"

    bl_label = "Export Anim USD Cache"

    bl_description = (

        "Export selected meshes as a deformation-only USD animation cache "

        "for Solaris animation layers (.usd)"

    )

    bl_options = {"REGISTER"}



    _session: UsdAnimCacheExportSession | UsdAnimCacheMultiExportSession | None = None

    _timer = None



    @classmethod

    def poll(cls, context: Context) -> bool:

        props = context.scene.monofx_pipeline_blender_props

        if props.anim_usd_export_running:

            return False

        asset_list.ensure_export_assets_refresh(context, props)

        if asset_list.enabled_export_target_count(props) <= 0:

            return False

        if asset_list.has_enabled_geo_targets(props):

            ok, _ = check_pxr_available()

            if not ok:

                return False

        return True



    def _cleanup_modal(self, context: Context) -> None:

        wm = context.window_manager

        if self._timer is not None:

            try:

                wm.event_timer_remove(self._timer)

            except Exception:

                pass

            self._timer = None

        try:

            wm.progress_end()

        except Exception:

            pass

        try:

            context.window.cursor_set("DEFAULT")

        except Exception:

            pass



    def _finish_cancelled(self, context: Context) -> set[str]:

        global _ACTIVE_ANIM_USD_SESSION

        props = context.scene.monofx_pipeline_blender_props

        self._cleanup_modal(context)

        asset_list.mark_export_cancelled(props)

        props.anim_usd_export_running = False

        props.anim_usd_status_report = "Export cancelled."

        _ACTIVE_ANIM_USD_SESSION = None

        self._session = None

        self.report({"WARNING"}, "Export cancelled.")

        return {"CANCELLED"}



    def _report_result(self, context: Context, result) -> set[str]:

        props = context.scene.monofx_pipeline_blender_props

        frame_start = self._session.frame_start if self._session else 0

        frame_end = self._session.frame_end if self._session else 0



        if not result.ok:

            asset_list.mark_export_error(props)

            props.anim_usd_status_report = result.error

            self.report({"ERROR"}, result.error)

            return {"CANCELLED"}



        asset_list.mark_export_complete(props)

        geo_paths = result.geo_filepaths or ([result.filepath] if result.filepath else [])

        if len(geo_paths) > 1:

            names = ", ".join(Path(p).name for p in geo_paths)

            dest = f"{len(geo_paths)} geo file(s): {names}"

        else:

            dest = str(result.filepath or geo_paths[0] if geo_paths else "")

        status = (

            f"Exported {result.mesh_count} mesh(es)"

            f"{f', 1 camera' if result.camera_count else ''}, "

            f"frames {frame_start}–{frame_end} "

            f"in {format_export_elapsed(result.elapsed_seconds)} → {dest}"

        )

        if result.camera_filepath:

            status += f" (+ {Path(result.camera_filepath).name})"

        props.anim_usd_status_report = status

        for warning in result.warnings[:5]:

            self.report({"WARNING"}, warning)

        self.report({"INFO"}, status)

        return {"FINISHED"}



    def invoke(self, context: Context, _event) -> set[str]:

        global _ACTIVE_ANIM_USD_SESSION

        props = context.scene.monofx_pipeline_blender_props



        jobs, plan_err = plan_geo_export_jobs(context, props)

        asset_list.refresh_export_assets(context, props, force=True)

        asset_list.reset_export_statuses(props)

        enabled_jobs = asset_list.filter_enabled_geo_jobs(jobs, props)

        export_camera = asset_list.is_camera_export_enabled(props)

        if not enabled_jobs and not export_camera:

            self.report({"ERROR"}, plan_err or "No export targets enabled.")

            return {"CANCELLED"}

        if enabled_jobs:

            ok_pxr, pxr_err = check_pxr_available()

            if not ok_pxr:

                self.report({"ERROR"}, pxr_err)

                return {"CANCELLED"}



        scene = context.scene

        if props.anim_usd_use_scene_range:

            frame_start = int(scene.frame_start)

            frame_end = int(scene.frame_end)

        else:

            frame_start = int(props.anim_usd_frame_start)

            frame_end = int(props.anim_usd_frame_end)



        fps = float(scene.render.fps) / float(scene.render.fps_base or 1.0)

        root_prim = str(props.anim_usd_root_prim or "")



        if not enabled_jobs:

            ok_path, filepath, path_err = path_ui.resolve_output_path(props)

            if not ok_path:

                self.report({"ERROR"}, path_err)

                return {"CANCELLED"}

            self._session = UsdAnimCacheExportSession(

                context,

                filepath,

                frame_start=frame_start,

                frame_end=frame_end,

                fps=fps,

                root_prim_override=root_prim,

                strict_topology=True,

                mesh_objects=[],

                export_camera=True,

                write_publish_meta=True,

                job_label="Camera",

            )

        elif len(enabled_jobs) == 1:

            job = enabled_jobs[0]

            meshes = resolve_geo_job_mesh_objects(

                job.mesh_names,

                source_publish_names=job.source_publish_names,

                context=context,

            )

            self._session = UsdAnimCacheExportSession(

                context,

                job.filepath,

                frame_start=frame_start,

                frame_end=frame_end,

                fps=fps,

                root_prim_override=root_prim,

                strict_topology=True,

                mesh_objects=meshes,

                export_camera=export_camera,

                write_publish_meta=True,

                job_label=job.publish_name,

            )

        else:

            self._session = UsdAnimCacheMultiExportSession(

                context,

                enabled_jobs,

                frame_start=frame_start,

                frame_end=frame_end,

                fps=fps,

                root_prim_override=root_prim,

                strict_topology=True,

                export_camera=export_camera,

            )



        try:

            err = self._session.begin()

        except Exception as exc:

            asset_list.mark_export_error(props)

            props.anim_usd_export_running = False

            props.anim_usd_status_report = str(exc)

            self.report({"ERROR"}, str(exc))

            self._session = None

            _ACTIVE_ANIM_USD_SESSION = None

            return {"CANCELLED"}



        if err:

            asset_list.mark_export_error(props)

            props.anim_usd_export_running = False

            props.anim_usd_status_report = err

            self.report({"ERROR"}, err)

            self._session = None

            _ACTIVE_ANIM_USD_SESSION = None

            return {"CANCELLED"}



        props.anim_usd_export_running = True

        _ACTIVE_ANIM_USD_SESSION = self._session

        wm = context.window_manager

        wm.progress_begin(0, self._session.total_steps)

        self._timer = wm.event_timer_add(0.01, window=context.window)

        wm.modal_handler_add(self)



        rig_count = len(enabled_jobs)

        if rig_count > 1:

            props.anim_usd_status_report = (

                f"Exporting {rig_count} geo USD file(s)…"

            )

        else:

            props.anim_usd_status_report = "Exporting USD animation cache…"

        return {"RUNNING_MODAL"}



    def modal(self, context: Context, event) -> set[str]:

        global _ACTIVE_ANIM_USD_SESSION

        session = self._session

        if session is None:

            self._cleanup_modal(context)

            context.scene.monofx_pipeline_blender_props.anim_usd_export_running = False

            _ACTIVE_ANIM_USD_SESSION = None

            return {"CANCELLED"}



        if event.type == "ESC":

            session.cancel()

            return self._finish_cancelled(context)



        if session._cancelled:

            return self._finish_cancelled(context)



        if event.type != "TIMER":

            return {"PASS_THROUGH"}



        err = session.step(units_per_tick=1)

        context.window_manager.progress_update(session.current_step)



        props = context.scene.monofx_pipeline_blender_props

        asset_list.update_export_statuses(props, session)



        if err:

            session.cancel()

            self._cleanup_modal(context)

            result = session.result

            result.error = err

            props.anim_usd_export_running = False

            _ACTIVE_ANIM_USD_SESSION = None

            self._session = None

            return self._report_result(context, result)



        if session.done:

            result = session.finish()

            self._cleanup_modal(context)

            props.anim_usd_export_running = False

            _ACTIVE_ANIM_USD_SESSION = None

            self._session = None

            return self._report_result(context, result)



        if session.status_label:

            props.anim_usd_status_report = (

                f"Exporting… {session.status_label} · {session.progress_time_label}"

            )

        return {"RUNNING_MODAL"}



    def execute(self, context: Context) -> set[str]:

        return self.invoke(context, None)





class MONOFX_OT_cancel_anim_usd_export(Operator):

    bl_idname = "wm.mono_fx_cancel_anim_usd_export"

    bl_label = "Cancel Anim USD Export"

    bl_description = "Cancel the running USD animation cache export"

    bl_options = {"REGISTER"}



    @classmethod

    def poll(cls, context: Context) -> bool:

        return bool(context.scene.monofx_pipeline_blender_props.anim_usd_export_running)



    def execute(self, context: Context) -> set[str]:

        global _ACTIVE_ANIM_USD_SESSION

        props = context.scene.monofx_pipeline_blender_props

        if _ACTIVE_ANIM_USD_SESSION is not None:

            _ACTIVE_ANIM_USD_SESSION.cancel()

            return {"FINISHED"}

        if props.anim_usd_export_running:

            asset_list.mark_export_cancelled(props)

            props.anim_usd_export_running = False

            props.anim_usd_status_report = "Export cancelled."

            self.report({"INFO"}, "Cleared stale export state.")

        return {"FINISHED"}


class MONOFX_OT_anim_usd_open_publish_folder(Operator):

    bl_idname = "wm.mono_fx_anim_usd_open_publish_folder"

    bl_label = "Open Publish Folder"

    bl_description = "Open the anim USD publish version folder in the file browser"

    bl_options = {"REGISTER"}

    def execute(self, context: Context) -> set[str]:

        props = context.scene.monofx_pipeline_blender_props

        ok, folder, err = path_ui.resolve_anim_publish_folder(props)

        if not ok:

            self.report({"ERROR"}, err)

            return {"CANCELLED"}

        target = folder.resolve()

        if not target.is_dir():

            publish_root = target.parent

            if publish_root.is_dir():

                target = publish_root.resolve()

                self.report(

                    {"INFO"},

                    f"Version folder not created yet; opened publish root: {target}",

                )

            else:

                self.report({"ERROR"}, f"Folder does not exist: {folder}")

                return {"CANCELLED"}

        bpy.ops.wm.path_open(filepath=str(target))

        return {"FINISHED"}


ANIM_USD_OPERATOR_CLASSES = (

    MONOFX_OT_export_anim_usd_cache,

    MONOFX_OT_cancel_anim_usd_export,

    MONOFX_OT_anim_usd_open_publish_folder,

)
