"""USD batch loader — Houdini entry point."""

from __future__ import annotations


def run(
    folder: str | None = None,
    *,
    mode: str | None = None,
    recursive: bool = False,
) -> None:
    from apps.houdini.usd_batch_loader import run as _run

    _run(folder=folder, mode=mode, recursive=recursive)  # type: ignore[arg-type]
