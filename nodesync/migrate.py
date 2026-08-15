"""
One-shot migration for projects written by NodeSync <= 1.3.1.

Older versions turned a data-block name into a filename with nothing more than

    name.replace('/', '_').replace('\\', '_')

which left trailing spaces, trailing dots, Windows-reserved characters and DOS
device names intact.  On Windows a component ending in a space or a dot cannot
be addressed by Explorer or `del` at all — the "ghost file" bug.  The same
scheme also collapsed distinct names onto one path ('A/B' and 'A:B' both give
'A_B.json'), so two node groups could silently overwrite each other's JSON.

utils.safe_filename() fixes this for everything written from now on, but
repositories created by an older version still hold the old names.  This module
finds them and renames them in place.

The mapping is recovered from the JSON *content*, not the filename: every file
records the real data-block name, so the correct destination is simply
safe_filename(data['name']).  That makes the migration robust even for files
whose name was mangled beyond recognition.

THIS MODULE IS TEMPORARY.  Once the user base has rolled past the version that
introduced safe_filename(), delete it together with operators/migrate_ops.py
and the panel button that calls it.
"""

import json
import os

from .project import ASSIGNMENTS_FILENAME, EMBEDDED_SHADER_OWNERS
from .utils import (
    TEMP_FILE_PREFIX,
    _clean_component,
    safe_texture_filename,
)


# ---------------------------------------------------------------------------
# Windows ghost-path access
# ---------------------------------------------------------------------------

def extended_path(path: str) -> str:
    """
    Return a form of `path` that the Windows API will accept verbatim.

    Normal Win32 calls strip trailing spaces and dots from a path before using
    it, which is why a file literally named 'Foo .json' cannot be opened,
    renamed or deleted by ordinary means — every attempt silently resolves to
    'Foo.json' instead.  Prefixing with \\\\?\\ disables that normalisation and
    is the only way to touch such a file.  No-op everywhere except Windows.
    """
    if os.name != 'nt':
        return path
    abs_path = os.path.abspath(path)
    if abs_path.startswith('\\\\?\\'):
        return abs_path
    if abs_path.startswith('\\\\'):
        # UNC share: \\server\share -> \\?\UNC\server\share
        return '\\\\?\\UNC\\' + abs_path[2:]
    return '\\\\?\\' + abs_path


def _exists(path: str) -> bool:
    return os.path.exists(extended_path(path))


def _rename(src: str, dst: str):
    os.replace(extended_path(src), extended_path(dst))


def _remove(path: str):
    os.remove(extended_path(path))


def _read_json(path: str):
    with open(extended_path(path), 'r', encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Legacy name reconstruction
# ---------------------------------------------------------------------------

def legacy_filename(name: str) -> str:
    """The bare filename NodeSync <= 1.3.1 would have written for `name`."""
    return name.replace('/', '_').replace('\\', '_')


def legacy_texture_filename(image_name: str) -> str:
    """The textures/ filename NodeSync <= 1.3.1 would have written."""
    safe = legacy_filename(image_name)
    if not os.path.splitext(safe)[1]:
        safe += '.png'
    return safe


def addressable(filename: str) -> str:
    """
    Strip a filename down to something the OS can actually open, rename and
    delete — without the disambiguating hash that safe_filename() adds.  Used
    to rescue ghost files we cannot map back to a data-block name: renaming
    them to an addressable form is strictly better than deleting them, because
    it preserves the data and hands control back to the user.
    """
    return _clean_component(filename) or '_unnamed'


def _is_ghost(filename: str) -> bool:
    """True if the OS cannot reliably address a file with this name."""
    return filename != addressable(filename)


def _unique(directory: str, filename: str, claimed: set) -> str:
    """Pick a free path in `directory`, avoiding names this run already took."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    n = 1
    while candidate in claimed or _exists(candidate):
        candidate = os.path.join(directory, f'{stem}_{n}{ext}')
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

# action kinds
RENAME    = 'rename'      # move src -> dst
SUPERSEDE = 'supersede'   # delete src; a correctly-named file already exists
RESCUE    = 'rescue'      # unmappable ghost; rename to something deletable


def _action(kind, src, dst, note):
    return {'kind': kind, 'src': src, 'dst': dst, 'note': note}


def _json_dirs(proj):
    """Every directory holding tracked JSON files."""
    dirs = [proj.nodes_dir, proj.shader_dir]
    for _collection, subdir in EMBEDDED_SHADER_OWNERS:
        dirs.append(os.path.join(proj.shader_dir, subdir))
    return dirs


def _expected_json_path(proj, data):
    """Where the current naming scheme says this file belongs."""
    owner_type = data.get('owner_type')
    if owner_type in {c for c, _s in EMBEDDED_SHADER_OWNERS}:
        owner_name = data.get('owner_name')
        if not owner_name:
            return None
        return proj.embedded_shader_file_path(owner_type, owner_name)
    name = data.get('name')
    if not name:
        return None
    return proj.node_file_path(name, data.get('type', 'GeometryNodeTree'))


def _collect_image_names(proj):
    """Every image name referenced by any tracked JSON in the project."""
    names = set()
    for directory in _json_dirs(proj):
        for filename in _listdir(directory):
            if not filename.endswith('.json') or filename == ASSIGNMENTS_FILENAME:
                continue
            try:
                data = _read_json(os.path.join(directory, filename))
            except Exception:
                continue
            for node in data.get('nodes', []):
                image_name = (node.get('type_specific') or {}).get('image_name')
                if image_name:
                    names.add(image_name)
    return names


def _listdir(directory):
    try:
        return sorted(os.listdir(extended_path(directory)))
    except OSError:
        return []


def scan(proj) -> list:
    """
    Work out what needs to change in `proj` without touching anything.
    Returns a list of action dicts; an empty list means the project is already
    on the current naming scheme.
    """
    actions = []
    claimed = set()   # destinations this plan already takes

    # --- tracked JSON files -------------------------------------------------
    for directory in _json_dirs(proj):
        for filename in _listdir(directory):
            if not filename.endswith('.json') or filename == ASSIGNMENTS_FILENAME:
                continue
            if filename.startswith(TEMP_FILE_PREFIX):
                continue
            src = os.path.join(directory, filename)

            try:
                data = _read_json(src)
            except Exception:
                # Unreadable, but if the *name* is the problem we can still
                # make it deletable.
                if _is_ghost(filename):
                    dst = _unique(directory, addressable(filename), claimed)
                    claimed.add(dst)
                    actions.append(_action(
                        RESCUE, src, dst,
                        'unreadable file with an un-deletable name'))
                continue

            expected = _expected_json_path(proj, data)
            if expected is None:
                if _is_ghost(filename):
                    dst = _unique(directory, addressable(filename), claimed)
                    claimed.add(dst)
                    actions.append(_action(
                        RESCUE, src, dst, 'no data-block name recorded'))
                continue

            if os.path.normpath(src) == os.path.normpath(expected):
                continue

            if expected in claimed:
                # Two files claim one destination — a genuine duplicate in the
                # repo.  Leave the second one alone rather than guess.
                continue

            if _exists(expected):
                actions.append(_action(
                    SUPERSEDE, src, None,
                    f"superseded by {os.path.basename(expected)}"))
            else:
                claimed.add(expected)
                actions.append(_action(
                    RENAME, src, expected, f"node tree '{data.get('name', '?')}'"))

    # --- textures -----------------------------------------------------------
    image_names = _collect_image_names(proj)
    wanted = {}    # current-scheme filename -> image name
    legacy = {}    # legacy filename         -> current-scheme filename
    for image_name in image_names:
        current = safe_texture_filename(image_name)
        wanted[current] = image_name
        legacy.setdefault(legacy_texture_filename(image_name), current)

    tex_dir = proj.textures_dir
    for filename in _listdir(tex_dir):
        if filename.startswith(TEMP_FILE_PREFIX):
            continue
        src = os.path.join(tex_dir, filename)

        if filename in wanted:
            continue    # already correct

        if filename in legacy:
            dst = os.path.join(tex_dir, legacy[filename])
            if dst in claimed:
                continue
            if _exists(dst):
                actions.append(_action(
                    SUPERSEDE, src, None,
                    f"superseded by {legacy[filename]}"))
            else:
                claimed.add(dst)
                actions.append(_action(
                    RENAME, src, dst, f"texture '{wanted[legacy[filename]]}'"))
            continue

        if _is_ghost(filename):
            dst = _unique(tex_dir, addressable(filename), claimed)
            claimed.add(dst)
            actions.append(_action(
                RESCUE, src, dst, 'texture with an un-deletable name'))

    return actions


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply(actions: list) -> tuple:
    """
    Carry out `actions`.  Returns (applied, errors) where applied is the list
    of actions that succeeded and errors is a list of 'file: reason' strings.
    Each action is independent — one failure never aborts the rest.
    """
    applied = []
    errors  = []
    for action in actions:
        src = action['src']
        try:
            if action['kind'] == SUPERSEDE:
                _remove(src)
            else:
                os.makedirs(os.path.dirname(action['dst']), exist_ok=True)
                _rename(src, action['dst'])
            applied.append(action)
        except Exception as e:
            errors.append(f"{os.path.basename(src)}: {e}")
            print(f"[NodeSync] Migration failed for '{src}': {e}")
    return applied, errors


def describe(action: dict, root: str) -> str:
    """One-line, repo-relative summary of an action for the confirm dialog."""
    def rel(path):
        try:
            return os.path.relpath(path, root)
        except ValueError:
            return path

    if action['kind'] == SUPERSEDE:
        return f"delete  {rel(action['src'])}  ({action['note']})"
    verb = 'rescue' if action['kind'] == RESCUE else 'rename'
    return f"{verb}  {rel(action['src'])}  →  {rel(action['dst'])}"


def count_pending(proj) -> int:
    """Cheap-to-call wrapper used to decide whether to show the UI button."""
    try:
        return len(scan(proj))
    except Exception as e:
        print(f"[NodeSync] Migration scan failed: {e}")
        return 0
