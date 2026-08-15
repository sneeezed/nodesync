# Changelog

## NodeSync 1.3.4

### Textures could leave a file Windows couldn't delete

An image whose name ended in a space was written to disk with that space intact, producing a file Explorer and `del` both refuse to touch. Blender names duplicate images `Wood.001`, and NodeSync read the trailing `.001 ` as a file extension, so it skipped adding `.png` and the space ended up at the end of the filename. Every name is now cleaned before it is used as a filename: illegal characters become underscores, trailing spaces and dots are stripped, and Windows device names like `CON` are prefixed. Existing broken files can be repaired with the migration button below.

### Two node groups could overwrite each other

Cleaning a name is lossy — `A/B` and `A:B` both became `A_B.json`, and whichever exported second replaced the first with no warning. Cleaned names now carry a short hash of the original, so distinct groups always land on distinct files. Names that need no cleaning are left alone, so ordinary projects keep readable filenames.

### Textures failed to reload after a clone

Images were written under a cleaned name but looked up under the raw one, so any image with a `/` in its name, or none, came back empty on import. Both sides now use the same name.

### A failed write could destroy the previous version

Writing a file truncates it before the new content goes in, so a write interrupted by a crash or a full disk left a broken file and took the last good copy with it. Writes now complete in a temporary file and are swapped into place only when finished.

### Export failures were invisible

Errors were printed to the system console, which most users never open. A commit where everything failed reported "No tracked node groups found in file" instead. Failures are now shown in the info bar and named individually, and a partial export warns which trees were left out.

### New: migration for older projects

Projects made before 1.3.4 still contain files written under the old scheme, including any undeletable ones. NodeSync detects them and shows a **Migrate Project Files** button in the Project panel. It lists every change before applying anything, then renames files to the current scheme, repairs names the OS cannot delete, and stages the result so your next commit records clean renames.

Commit your work first. Everyone sharing a repository needs 1.3.4 before you push a migration, or an older version will undo it.

---

## NodeSync 1.3.1

### Faster reverts on large projects

Checking out an older commit used to clear and rebuild every tracked node group through Blender's Python API, even ones that were byte-identical to the target commit. NodeSync now uses the diff it already computes to reimport only the node groups that actually changed between your current state and the target commit (unchanged groups stay in `bpy.data` untouched). Reverts that only modify a handful of trees in a project with many tracked groups now complete dramatically faster.

### Commit operator no longer freezes Blender

Auto-push on commit previously ran on a background thread, which could conflict with Blender's main-thread-only data access and occasionally hang the UI. The commit pipeline has been rewritten as a modal operator that drives Git as a sequence of subprocess steps — each `git add`, `git commit`, `git log`, `git rev-parse`, `git branch`, and `git push` runs as its own non-blocking process polled from a timer. The UI stays responsive during long pushes, errors from any individual step are reported cleanly instead of disappearing into a thread, and commits no longer race against texture export or screenshot capture.
