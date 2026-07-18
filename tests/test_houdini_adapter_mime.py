"""Tests for Houdini adapter helpers that do not require hou."""

from __future__ import annotations

from apps.houdini.adapter import split_node_path_payload


def test_split_node_path_payload_tabs_and_newlines() -> None:
    assert split_node_path_payload("/obj/geo1/box1\t/obj/geo1/xform1") == [
        "/obj/geo1/box1",
        "/obj/geo1/xform1",
    ]
    assert split_node_path_payload("/obj/a\n/obj/b\n/obj/a") == ["/obj/a", "/obj/b"]


def test_split_node_path_payload_ignores_noise() -> None:
    assert split_node_path_payload("") == []
    assert split_node_path_payload("hello world") == []
    assert split_node_path_payload('"/obj/cam1", /obj/cam2') == ["/obj/cam1", "/obj/cam2"]
