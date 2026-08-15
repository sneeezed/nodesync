# NodeSync

![NodeSync Demo](NodeSyncDemo.gif)

**NodeSync** is a Blender addon that brings Git-based version control to your node trees. It tracks Geometry Nodes, Shader Nodes (materials, worlds, and lights), and the image textures they reference — letting you commit, branch, push, pull, and restore your setups just like source code, with support for any Git remote (GitHub, GitLab, Codeberg, Gitea, Bitbucket, self-hosted, ...) and a live diff overlay.

Each node tree is serialized to a JSON file and tracked individually in Git, giving you a precise history of every change. Branch for experiments, collaborate through any Git host you already use, and restore any version in seconds.

---

## What It Does

- **Commit & restore** any version of your Geometry and Shader node trees
- **Branch** to experiment without breaking your main setup
- **Push/pull** to/from any Git remote for backup and collaboration
- **Auto-push on commit** — optionally publish every commit to your remote without a separate click
- **Visualize diffs** with a color overlay (added / modified / deleted nodes), with an adjustable diff base
- **Multi-lane history coloring** — each commit is colored by the most-specific branch that reaches it, so the default branch owns shared ancestors
- **Resolve merge conflicts** when two people edit the same group
- **Filter history** by the currently viewed node tree, or by Geometry vs Shader
- **Selective pull** — pick which incoming groups to apply and which to keep local
- **Track image textures** referenced by shader nodes (opt-in)
- **Scene assignments** — material slots and Geometry Nodes modifier links travel with the repo, so scene wiring survives across clones, machines, and reverts

---

## Installation

1. Download or build `nodesync.zip`
2. In Blender: **Edit → Preferences → Add-ons → Install** → select `nodesync.zip`
3. Enable the addon

The NodeSync panel appears in both the **Geometry Node Editor** and **Shader Editor** N-panel under the **NodeSync** tab.

---

## Getting Started

### Initialize a New Project

1. Open the NodeSync panel in the Geometry or Shader Node editor
2. Set your **Project Root** folder (defaults to the `.blend` file directory)
3. Click **Init New Project** — this creates a `nodes/` folder, a `.nodesync` config file, and runs `git init`

### Make Your First Commit

1. Type a message in the **Commit message** field
2. Click **Commit** — all Geometry and Shader node trees are serialized to JSON and committed

### Connect to a Git Remote (Optional)

1. Create an empty repo on your Git host of choice (GitHub, GitLab, Codeberg, Gitea, Bitbucket, self-hosted Forgejo, ...).
2. Paste the repo URL into the **Remote URL** field and click **Set Remote**.
3. Add your credentials in **Edit → Preferences → Add-ons → NodeSync**:
   - **Personal Access Token** — generated from your Git host's user settings (scope: write to your repo). Required for pushing; reading public repos works without one.
   - **Remote Username** — host-specific. Leave blank for GitHub or Azure DevOps; use `oauth2` for GitLab; `x-token-auth` for Bitbucket; your account name for Codeberg / Gitea / Forgejo.
4. Click **Push ↑** to upload.

> SSH URLs (`git@host:user/repo.git`) work too — they bypass the token field entirely and use your system SSH agent.

### Clone an Existing Project

1. Paste the Git repository URL and choose a local folder.
2. Click **Clone from Git Remote** — all node trees (geometry and shader) are imported automatically.

---

## Features

### Version Control

| Action | Description |
|--------|-------------|
| **Commit** | Saves all node trees to JSON and creates a Git commit |
| **Checkout** | Restores your node trees to any previous commit |
| **History** | Browse up to 300 commits with author, date, and branch info; the bookmark icon tracks whichever commit is currently loaded |
| **History Filter** | Show only commits that touched the currently open node tree, or filter by Geometry vs Shader |
| **View Diff** | Overlays the node graph with colors showing what changed vs the chosen diff base |
| **Diff Base** | Choose any prior commit (not just HEAD) to diff the current state against |

**Diff colors:**
- **Green** — node was added since last commit
- **Orange** — node was modified
- **Red ghost** — node was deleted (shown as a placeholder)

### Shader Node Tracking

NodeSync automatically exports every shader tree when you commit or save your `.blend` file. The on-disk layout is:

```
nodes/
  _scene_assignments.json        ← which objects use which materials / GN groups
  MyGeometryGroup.json           ← standalone geometry node groups
  shader/
    MyShaderGroup.json           ← standalone shader node groups
    materials/
      Stone.json                 ← Material "Stone" node tree
      Metal.json
    worlds/
      HDRI_Sky.json              ← World lighting node tree
    lights/
      AreaLight.json             ← Light node tree
textures/
  rock_diffuse.png               ← copied by "Track Shader Textures"
```

### Scene Assignments File

Alongside the per-tree JSONs, NodeSync writes a single `nodes/_scene_assignments.json` on every commit and `.blend` save. It records two things:

- **material_slots** — for each object, which material name occupies each of its material slots
- **modifier_links** — for each object, which Geometry Nodes node group each `NODES`-type modifier points at

```json
{
  "version": 1,
  "material_slots": {
    "Cube":     ["Stone", null, "Metal"],
    "Sphere":   ["Stone"]
  },
  "modifier_links": {
    "Plane":    { "GeometryNodes": "MyGeometryGroup" }
  }
}
```

This file is **read on every revert, branch switch, pull, and clone**. After NodeSync re-imports the node trees, it walks this map and re-attaches materials and GN modifier groups to any object slot that's currently empty. It never overwrites an existing assignment, so reassigning a slot manually after revert is safe — the next pull won't undo it.

Because this lives in git and not in memory, slot assignments survive across Blender sessions, machines, and clones — anyone who checks out the commit gets the same scene wiring.

### Image Texture Tracking

When **Track Shader Textures** is enabled (Addon Preferences → Commit Behaviour):

- On each commit, NodeSync walks every Shader Image Texture node in all tracked shader trees
- Each referenced image is copied into `textures/<name>` and staged for the commit
- Packed images and generated images are written via Blender's render pipeline
- External images are copied verbatim from their source path

This means a fresh `git clone` + **Clone from Git Remote** gives a fully reproducible shader setup.

Image names are sanitized before they hit disk (see [Filenames on disk](#filenames-on-disk)). The image's real name is stored inside the JSON, so the node reconnects to the right image on import no matter what the file ended up being called.

### Filenames on disk

Blender allows characters in a data-block name that a filesystem does not — `/`, `:`, trailing spaces, trailing dots. Written out verbatim, some of those produce files the OS mangles: on Windows a name ending in a space or a dot cannot be opened, renamed or deleted through Explorer or `del`, because Win32 silently resolves the path to a different name.

NodeSync sanitizes every name before using it as a filename:

- path separators, `<>:"|?*` and control characters become `_`
- leading and trailing whitespace and trailing dots are stripped
- Windows device names (`CON`, `NUL`, `COM1`…) are prefixed with `_`
- a name that had to be changed gets a short hash of the original appended, so two different node groups can never collide on one file

| Data-block name | File written |
|-----------------|--------------|
| `Rock Generator` | `Rock Generator.json` |
| `Wood/Bar` | `Wood_Bar~d1aee731.json` |
| `Wood:Bar` | `Wood_Bar~7298d2b5.json` |
| `Metal ` (trailing space) | `Metal~4acf34d4.json` |

Names that need no cleaning are left exactly as they are, so ordinary projects still have readable filenames. The hash only appears where it prevents a real collision or an unusable file.

### Migrating projects made before 1.3.4

Projects created by an earlier version still contain files written under the old scheme. When NodeSync detects them it shows a **Migrate Project Files** button in the Project panel, with a count of what needs changing.

The button opens a dialog listing every rename before anything happens. Applying it renames files to the current scheme, repairs names the OS cannot delete, and stages the result so your next commit records clean renames rather than a pile of deletions. Each file's correct name is recovered from the JSON contents, not from its current filename, so it works even on files whose names were mangled beyond recognition.

Two things worth knowing:

- **Commit or stash first.** The migration edits files in your project folder.
- **Everyone on a shared repo needs 1.3.4 before you push a migration.** An older version will re-create the old filenames and undo it.

One case cannot be repaired: if two node groups whose names differed only in an illegal character (`A/B` and `A:B`) both existed, the older version already overwrote one with the other on disk. Migration fixes the naming going forward but cannot recover data that was lost before it ran.

### Branching

- **Create Branch** from the Branches panel
- **Switch Branch** — reimports all node trees from the target branch
- Each branch gets a unique color swatch shown in the history list
- History coloring uses branch lanes: shared ancestors are colored by the default branch, and feature branches keep their own color only on commits that aren't reachable from `main`

### Push & Pull

- **Push ↑** — sends your commits to the configured Git remote
- **Auto-Push on Commit** — turn on in addon preferences to push automatically after every commit
- **Pull ↓** — fetches and shows a per-group selection dialog so you can choose which incoming changes to apply; reimports changed trees automatically and advances the history bookmark to the new HEAD
- On **merge conflicts**, a Conflicts panel appears with per-file options:
  - **Keep Mine** — use your local version
  - **Use Remote** — use the incoming version
  - **Complete Merge** / **Abort Merge** when done
- Per-file import failures during pull surface in the Blender info bar instead of being silently swallowed

### Addon Preferences

| Preference | Description |
|------------|-------------|
| **Remote Username** | Host-specific username for HTTPS auth. Blank for GitHub / Azure DevOps; `oauth2` for GitLab; `x-token-auth` for Bitbucket; account name for Codeberg / Gitea / Forgejo |
| **Personal Access Token** | Token used as the password for HTTPS push/pull. Generated in your Git host's user settings; needs write-repository scope |
| **Auto-Push on Commit** | Automatically push after every commit when a remote is configured |
| **Screenshot Node Editor on Commit** | Capture a screenshot of the node editor and attach it to the commit |
| **Track Shader Textures** | Copy image textures from Shader Image Texture nodes into `textures/` on commit |

---

## How It Works (Technical)

Each node tree is serialized to a JSON file containing:
- The full node interface (inputs/outputs with types, defaults, min/max)
- Every node with its type, position, properties, and socket defaults
- All links between nodes
- For Geometry Nodes trees: the `is_modifier` and `is_tool` flags, so reconstructed groups appear in the modifier dropdown and Tool panel exactly as they did on the source machine
- For embedded material/world/light trees: `owner_type` and `owner_name` tags so the deserializer knows which Blender data-block to attach to

In addition, `nodes/_scene_assignments.json` records which objects use which materials (per slot) and which GN modifiers point at which node groups, so scene wiring is restored automatically on revert / branch-switch / pull / clone.

On checkout or pull, NodeSync reconstructs every node tree from JSON in dependency order (nested groups first), then applies the scene-assignments map to re-attach materials and modifier groups to any empty slot. Reconstructed groups also get a fake user so they stay visible and don't linger as orphan data-blocks. Socket matching uses Blender's internal socket identifiers for stability, keeping git history clean even when sockets are reordered.

Every write is atomic: content goes to a scratch file in the same directory and is renamed over the target only once it is complete. A write interrupted by a crash, a full disk or a permissions change leaves the previous version untouched instead of a truncated file that fails every later import. The same applies to textures — both Blender's image writer and a plain file copy create the destination before filling it, so a failure partway used to leave a zero-byte file behind and destroy the previous commit's copy.

Failures during export are reported in the Blender info bar and named individually in the system console. Earlier versions printed them to the console only, which meant a commit where every export failed reported "No tracked node groups found in file" — the wrong diagnosis entirely.

Git operations run via subprocess. No external Python dependencies required — only the standard library and Blender's `bpy`.

---

## Requirements

- Blender 4.x
- Git installed and on your PATH
- A Personal Access Token from your Git host (GitHub, GitLab, Codeberg, Gitea, Bitbucket, ...) — only needed for pushing or for pulling private repos. Public-repo reads work without one, and SSH URLs use your system SSH agent instead
