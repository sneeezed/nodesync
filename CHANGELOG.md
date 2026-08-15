# Changelog

## NodeSync 1.3.4

### Fixed: textures could leave a file Windows couldn't delete

A texture whose image name ended in a space was written to disk with that space intact, producing a file Explorer and `del` both refuse to touch — every attempt silently resolves to a different path. The cause was narrow: NodeSync only appended `.png` when Python reported the name as having no extension, and for an image called `Wood.001 ` or `Tex.png ` it reports a trailing `.001 ` or `.png ` as the extension, so nothing was appended and the space landed at the end of the filename. Blender names duplicate images `Wood.001` by default, so this was easy to hit without doing anything unusual. Every name NodeSync writes is now sanitized first: path separators and the characters Windows forbids become underscores, trailing spaces and dots are stripped, and Windows device names (`CON`, `NUL`, `COM1`) are prefixed. Existing broken files can be repaired with the new migration button below.

### Fixed: two node groups could silently overwrite each other

Cleaning a name is lossy — `A/B` and `A:B` both used to become `A_B.json`, and whichever exported second overwrote the first with no warning at all. Any name that has to be changed now carries a short hash of the original, so distinct node groups always land on distinct files. Names that need no cleaning are left exactly as they were, so ordinary projects keep readable filenames and nothing is renamed unnecessarily. The same fix applies to textures, where an image name containing an illegal character previously produced a doubled or misplaced extension: `Wood/Bar.png` came out as `Wood_Bar.png~<hash>.png`, and a `.jpg` could end up labeled `.png`.

### Fixed: textures failed to reload after a fresh clone

The exporter sanitized image names before writing them, but the importer looked for the raw, unsanitized name. Any image whose name contained a `/` or had no file extension was therefore written under one name and searched for under another, so it silently failed to resolve on import and the Image Texture node came back empty. Both sides now use the same function, so what gets written is always what gets looked up.

### Fixed: a failed write could destroy the previous commit's file

Both Blender's image writer and a plain file copy create and truncate the destination before they start filling it. A write interrupted partway — full disk, lost permissions, a crash — left a zero-byte or half-copied file in the repository and took the previous commit's good copy with it. For JSON the result was worse: a truncated file that failed every subsequent import with no indication why. All writes now go to a scratch file and are renamed into place only once complete, so an interrupted write leaves the previous version untouched. Scratch files left behind by a hard crash are swept automatically so they can never be picked up by a commit.

### Fixed: export failures were invisible

Errors during export were caught and printed to the system console, which most users never open. If every export failed, the commit operator reported "No tracked node groups found in file" — a completely wrong diagnosis that sent people looking for a problem in the wrong place. Texture failures were worse still and could never surface at all, so a commit where no texture saved looked entirely successful. Failures are now reported in the info bar, named individually, and a partial export warns you which trees are not in the commit.

### New: one-click migration for older projects

Projects created before 1.3.4 still contain files written under the old naming scheme, including any undeletable ones. NodeSync now detects them and shows a **Migrate Project Files** button in the Project panel with a count of what needs changing. It opens a dialog listing every rename before touching anything, then renames files to the current scheme, repairs names the operating system cannot delete, and stages the result so your next commit records clean renames instead of a pile of unexplained deletions. Each file's correct destination is recovered from the JSON contents rather than its current filename, so it works even on files whose names were mangled beyond recognition.

Commit or stash your work before running it, and note that everyone sharing a repository needs 1.3.4 before you push a migration — an older version will re-create the old filenames and undo it.

---

## NodeSync 1.3.1

### Faster reverts on large projects

Checking out an older commit used to clear and rebuild every tracked node group through Blender's Python API, even ones that were byte-identical to the target commit. NodeSync now uses the diff it already computes to reimport only the node groups that actually changed between your current state and the target commit (unchanged groups stay in `bpy.data` untouched). Reverts that only modify a handful of trees in a project with many tracked groups now complete dramatically faster.

### Commit operator no longer freezes Blender

Auto-push on commit previously ran on a background thread, which could conflict with Blender's main-thread-only data access and occasionally hang the UI. The commit pipeline has been rewritten as a modal operator that drives Git as a sequence of subprocess steps — each `git add`, `git commit`, `git log`, `git rev-parse`, `git branch`, and `git push` runs as its own non-blocking process polled from a timer. The UI stays responsive during long pushes, errors from any individual step are reported cleanly instead of disappearing into a thread, and commits no longer race against texture export or screenshot capture.
