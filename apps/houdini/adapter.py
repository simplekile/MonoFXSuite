"""
Thin Houdini adapter — only place that imports hou.

Tool controllers in tools/* use this module to talk to Houdini.
Core and logic must never import hou.
"""

from __future__ import annotations

from typing import Any, List, Optional

try:
    import hou
except ImportError:
    hou = None  # type: ignore[assignment]


def is_available() -> bool:
    """True if running inside Houdini (hou is available)."""
    return hou is not None


def get_hip_path() -> Optional[str]:
    """Current .hip file path, or None if not saved."""
    if not is_available():
        return None
    path = hou.hipFile.path()
    return path if path else None


def get_selected_nodes() -> List[Any]:
    """Selected nodes in the current network editor context."""
    if not is_available():
        return []
    return list(hou.selectedNodes())


def get_node_by_path(path: str) -> Any:
    """Resolve node by path; returns None if not found."""
    if not is_available():
        return None
    try:
        return hou.node(path)
    except Exception:
        return None


def get_main_qt_window() -> Any:
    """Main Houdini window as Qt object for parenting dialogs. None if not in Houdini."""
    if not is_available():
        return None
    try:
        return hou.ui.mainQtWindow()
    except Exception:
        return None


def ui_display_message(message: str, title: str = "MonoFX") -> None:
    """Display a message in Houdini (dialog)."""
    if not is_available():
        print(message)
        return
    try:
        hou.ui.displayMessage(message, title=title)
    except Exception:
        hou.ui.displayMessage(message)


# ----- Geometry / SOP (for split by path, name, material) -----


def is_sop_node(node: Any) -> bool:
    """True if node is a SOP node (has .geometry()). Use this to avoid OBJ vs SOP confusion."""
    if not is_available() or node is None:
        return False
    try:
        return isinstance(node, hou.SopNode)
    except Exception:
        return False


def get_geometry_from_node(node: Any) -> Any:
    """Get hou.Geometry from a SOP node. Returns None if not a SOP or no geometry."""
    if not is_available() or node is None or not is_sop_node(node):
        return None
    try:
        return node.geometry()
    except Exception:
        return None


def get_unique_string_attribute_values(node: Any, attribute_name: str) -> List[str]:
    """
    Get unique string values of an attribute on geometry (primitives or points).
    Tries primitives first, then points. Returns [] if node is not SOP or attr missing.
    """
    geo = get_geometry_from_node(node)
    if geo is None:
        return []
    seen: set = set()
    out: List[str] = []
    for prim in geo.prims():
        try:
            val = prim.stringAttribValue(attribute_name)
            if val is not None and val not in seen:
                seen.add(val)
                out.append(val)
        except Exception:
            pass
    if out:
        return sorted(out)
    for pt in geo.points():
        try:
            val = pt.stringAttribValue(attribute_name)
            if val is not None and val not in seen:
                seen.add(val)
                out.append(val)
        except Exception:
            pass
    return sorted(out) if out else []


def get_string_attribute_names_from_geometry(node: Any) -> List[str]:
    """
    Get list of string attribute names on geometry (primitives then points).
    Common: path, name, shop_materialpath, etc.
    Uses primAttribs()/pointAttribs() and filters by dataType() == String.
    """
    geo = get_geometry_from_node(node)
    if geo is None:
        return []
    names: set = set()
    try:
        for attrib in geo.primAttribs():
            if attrib.dataType() == hou.attribData.String:
                names.add(attrib.name())
        for attrib in geo.pointAttribs():
            if attrib.dataType() == hou.attribData.String:
                names.add(attrib.name())
    except Exception:
        pass
    return sorted(names)


def get_value_counts_by_string_attribute(node: Any, attribute_name: str) -> dict:
    """
    Return dict: attribute_value -> count. Uses bulk API (primStringAttribValues /
    pointStringAttribValues) for speed on large geometry. Empty dict if not SOP or attr missing.
    """
    geo = get_geometry_from_node(node)
    if geo is None:
        return {}
    try:
        values = geo.primStringAttribValues(attribute_name)
    except Exception:
        try:
            values = geo.pointStringAttribValues(attribute_name)
        except Exception:
            return {}
    if not values:
        try:
            values = geo.pointStringAttribValues(attribute_name)
        except Exception:
            return {}
    from collections import Counter
    counts = Counter(values)
    # Merge None into "" for display
    if None in counts:
        counts[""] = counts.get("", 0) + counts.pop(None)
    return dict(counts)


def get_primitive_groups_by_attribute(node: Any, attribute_name: str) -> dict:
    """
    Return dict: attribute_value -> list of primitive numbers (prim_id).
    Empty dict if not SOP or attribute missing. Prefer get_value_counts_by_string_attribute
    for report/preview (faster); use this only when indices are needed.
    """
    geo = get_geometry_from_node(node)
    if geo is None:
        return {}
    groups: dict = {}
    for prim in geo.prims():
        try:
            val = prim.stringAttribValue(attribute_name)
            if val is None:
                val = ""
            if val not in groups:
                groups[val] = []
            groups[val].append(prim.number())
        except Exception:
            pass
    if not groups:
        for pt in geo.points():
            try:
                val = pt.stringAttribValue(attribute_name)
                if val is None:
                    val = ""
                if val not in groups:
                    groups[val] = []
                groups[val].append(pt.number())
            except Exception:
                pass
    return groups


def get_node_name(node: Any) -> str:
    """Get Houdini node name (not path)."""
    if not is_available() or node is None:
        return ""
    try:
        return node.name()
    except Exception:
        return ""


def set_node_name(node: Any, new_name: str) -> bool:
    """Set Houdini node name. Returns True on success."""
    if not is_available() or node is None:
        return False
    try:
        node.setName(new_name)
        return True
    except Exception:
        return False


def get_string_parms_for_node(node: Any) -> List[tuple]:
    """
    Get (parm_name, current_value) for all string-type parms on node.
    Returns list of (name, value) for use in search/replace.
    """
    if not is_available() or node is None:
        return []
    result: List[tuple] = []
    try:
        for p in node.parms():
            if p.parmTemplate().type() == hou.parmTemplateType.String:
                result.append((p.name(), p.evalAsString()))
    except Exception:
        pass
    return result


def set_parm_value(node: Any, parm_name: str, value: str) -> bool:
    """Set a string parm on a node. Returns True on success."""
    if not is_available() or node is None:
        return False
    try:
        p = node.parm(parm_name)
        if p is not None:
            p.set(value)
            return True
    except Exception:
        pass
    return False


def get_nodes_in_current_network(include_subnets: bool = True) -> List[Any]:
    """
    Get all nodes in current network editor context (hou.pwd() and its descendants).
    include_subnets: if True, recurse into subnets. Returns flat list.
    """
    if not is_available():
        return []
    try:
        pwd = hou.pwd()
        if pwd is None:
            return []
        nodes: List[Any] = [pwd]
        if include_subnets:
            nodes.extend(pwd.allSubChildren())
        return nodes
    except Exception:
        return []


def get_all_nodes_under(node: Any) -> List[Any]:
    """Return list of node and all descendants."""
    if not is_available() or node is None:
        return []
    out: List[Any] = [node]
    try:
        for c in node.allSubChildren():
            out.append(c)
    except Exception:
        pass
    return out


def detect_network_tags_for_parent(parent: Any) -> list[str]:
    """
    Detect network tag(s) for a parent node (SOP, VOP, LOP, OBJ, DOP, CHOP, COP2, TOP).
    Returns list of strings like ["SOP"].
    """
    if not is_available() or parent is None:
        return []
    try:
        import hou  # type: ignore[import]
    except Exception:
        return []
    try:
        # Prefer childTypeCategory for network containers; fall back to node type category.
        cat = None
        try:
            cat = parent.childTypeCategory()
        except Exception:
            pass
        if cat is None:
            try:
                cat = parent.type().category()
            except Exception:
                cat = None
        if cat is None:
            return []
        mapping = {
            hou.sopNodeTypeCategory(): "SOP",
            hou.vopNodeTypeCategory(): "VOP",
            hou.lopNodeTypeCategory(): "LOP",
            hou.objNodeTypeCategory(): "OBJ",
            hou.dopNodeTypeCategory(): "DOP",
            hou.chopNodeTypeCategory(): "CHOP",
            hou.cop2NodeTypeCategory(): "COP2",
            getattr(hou, "topNodeTypeCategory", lambda: None)(): "TOP",
        }
        for k, tag in mapping.items():
            if k is not None and cat == k:
                return [tag]
    except Exception:
        return []
    return []


def detect_network_tags_for_items(parent: Any, items: List[Any]) -> list[str]:
    """Wrapper for detect_network_tags_for_parent; kept for future per-item logic."""
    return detect_network_tags_for_parent(parent)


def create_node(parent: Any, node_type: str, name: Optional[str] = None) -> Any:
    """Create a node inside parent. node_type e.g. 'partition', 'blast'. Returns new node or None."""
    if not is_available() or parent is None:
        return None
    try:
        category = parent.childTypeCategory()
        node = parent.createNode(node_type, node_name=name)
        return node
    except Exception:
        return None


def set_node_input(node: Any, input_index: int, source_node: Any) -> bool:
    """Connect source_node to node's input input_index (0-based)."""
    if not is_available() or node is None or source_node is None:
        return False
    try:
        node.setInput(input_index, source_node)
        return True
    except Exception:
        return False


def set_parm(node: Any, parm_name: str, value: Any) -> bool:
    """Set parm by name. value can be str, int, float. Returns True on success."""
    if not is_available() or node is None:
        return False
    try:
        p = node.parm(parm_name)
        if p is not None:
            p.set(value)
            return True
    except Exception:
        pass
    return False


# ----- Node Preset Library (save/load items to file) -----


def get_selected_network_items() -> tuple[Any, List[Any]]:
    """
    Selected network items (nodes, sticky notes, boxes) that share the same parent.
    Returns (parent_node, items) or (None, []) if none selected or mixed parents.
    """
    if not is_available():
        return (None, [])
    try:
        items = list(hou.selectedItems())
        if not items:
            return (None, [])
        parent = items[0].parent()
        if parent is None:
            return (None, [])
        for item in items:
            if item.parent() != parent:
                return (None, [])
        return (parent, items)
    except Exception:
        return (None, [])


def get_current_network_parent() -> Any:
    """
    Network node to use as parent when inserting presets.

    Prefer the active Network Editor pane's pwd (matches what user is looking at),
    and fall back to hou.pwd().
    """
    if not is_available():
        return None
    try:
        # Prefer network editor context (shelf tools often have ambiguous hou.pwd()).
        try:
            pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if pane is not None:
                pwd = pane.pwd()
                if pwd is not None:
                    return pwd
        except Exception:
            pass

        pwd = hou.pwd()
        return pwd
    except Exception:
        return None


def save_items_to_file(
    parent: Any,
    items: List[Any],
    file_path: str,
    save_hda_fallbacks: bool = False,
) -> bool:
    """Save child items to a file (e.g. .cpio). parent.saveItemsToFile(items, path)."""
    if not is_available() or parent is None or not items:
        return False
    try:
        parent.saveItemsToFile(items, file_path, save_hda_fallbacks=save_hda_fallbacks)
        return True
    except Exception:
        return False


def load_items_from_file(
    parent: Any,
    file_path: str,
    ignore_load_warnings: bool = False,
) -> bool:
    """Load items from file into parent network. parent.loadItemsFromFile(path)."""
    if not is_available() or parent is None:
        return False
    try:
        # loadItemsFromFile must be called on a network/container node.
        target = parent
        try:
            # If a non-network node is passed (e.g. SOP node), insert into its parent network.
            if hasattr(target, "isNetwork") and not target.isNetwork():
                target = target.parent()
        except Exception:
            pass

        if target is None:
            return False

        target.loadItemsFromFile(file_path, ignore_load_warnings=ignore_load_warnings)
        return True
    except Exception:
        return False


def load_items_from_file_ex(
    parent: Any,
    file_path: str,
    ignore_load_warnings: bool = False,
) -> tuple[bool, str]:
    """Same as load_items_from_file, but returns (ok, error_message)."""
    if not is_available() or parent is None:
        return (False, "Houdini is not available or target parent is None.")
    try:
        target = parent
        try:
            if hasattr(target, "isNetwork") and not target.isNetwork():
                target = target.parent()
        except Exception:
            pass
        if target is None:
            return (False, "Cannot resolve a network container to paste into.")
        # Extra safety: ensure target is a network/container.
        try:
            if hasattr(target, "isNetwork") and not target.isNetwork():
                return (False, f"Target is not a network: {getattr(target, 'path', lambda: target)()}")
        except Exception:
            pass

        # Clear selection so we can detect which items were loaded.
        try:
            hou.clearAllSelected()
        except Exception:
            pass

        target.loadItemsFromFile(file_path, ignore_load_warnings=ignore_load_warnings)

        # Try to offset newly loaded items to the center of the active network editor.
        try:
            pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            new_items = list(hou.selectedItems())
            if pane is not None and new_items:
                # Compute average position of new items.
                avg_x = sum(it.position().x() for it in new_items) / len(new_items)
                avg_y = sum(it.position().y() for it in new_items) / len(new_items)
                avg_pos = hou.Vector2(avg_x, avg_y)

                # Visible bounds center as target.
                vb = pane.visibleBounds()
                center = hou.Vector2((vb.min().x() + vb.max().x()) * 0.5, (vb.min().y() + vb.max().y()) * 0.5)
                delta = center - avg_pos

                for it in new_items:
                    try:
                        pos = it.position()
                        it.setPosition(hou.Vector2(pos.x() + delta.x(), pos.y() + delta.y()))
                    except Exception:
                        continue
        except Exception:
            # If centering fails, we still consider the load successful.
            pass

        return (True, "")
    except Exception as e:
        try:
            tpath = target.path() if target is not None and hasattr(target, "path") else str(target)
        except Exception:
            tpath = "<unknown>"
        try:
            ttype = target.type().name() if target is not None and hasattr(target, "type") else "<unknown>"
        except Exception:
            ttype = "<unknown>"

        msg = str(e).strip()
        if not msg:
            msg = repr(e)
        return (False, f"{msg} (file={file_path}, target={tpath}, type={ttype})")
