# NodeSync

![NodeSync Demo](NodeSyncDemo.gif)

**NodeSync** is a Blender addon that brings Git-based version control to your node trees. It tracks Geometry Nodes, Shader Nodes (materials, worlds, and lights), and the image textures they reference — letting you commit, branch, push, pull, and restore your setups just like source code, with full GitHub integration and a live diff overlay.

Each node tree is serialized to a JSON file and tracked individually in Git, giving you a precise history of every change. Branch for experiments, collaborate through GitHub, and restore any version in seconds.

---

## What It Does

- **Commit & restore** any version of your Geometry and Shader node trees
- **Branch** to experiment without breaking your main setup
- **Push/pull** to/from GitHub for backup and collaboration
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

### Connect to GitHub (Optional)

1. Create an empty repo on GitHub
2. Paste the repo URL into the **Remote URL** field and click **Set Remote**
3. Add your GitHub Personal Access Token (PAT) in **Edit → Preferences → Add-ons → NodeSync**
4. Click **Push ↑** to upload

### Clone an Existing Project

1. Paste the GitHub URL and choose a local folder
2. Click **Clone from GitHub** — all node trees (geometry and shader) are imported automatically

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

This means a fresh `git clone` + **Clone from GitHub** gives a fully reproducible shader setup.

### Branching

- **Create Branch** from the Branches panel
- **Switch Branch** — reimports all node trees from the target branch
- Each branch gets a unique color swatch shown in the history list
- History coloring uses GitHub-style lanes: shared ancestors are colored by the default branch, and feature branches keep their own color only on commits that aren't reachable from `main`

### Push & Pull

- **Push ↑** — sends your commits to GitHub
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
| **GitHub Personal Access Token** | Classic PAT with `repo` scope for push/pull |
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

Git operations run via subprocess. No external Python dependencies required — only the standard library and Blender's `bpy`.

---

## Requirements

- Blender 4.x
- Git installed and on your PATH
- GitHub PAT with `repo` scope (for push/pull only)
