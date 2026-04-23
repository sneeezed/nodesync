# NodeSync

**NodeSync** is a Blender addon that brings Git-based version control to your node trees. It tracks Geometry Nodes, Shader Nodes (materials, worlds, and lights), and the image textures they reference — letting you commit, branch, push, pull, and restore your setups just like source code, with full GitHub integration and a live diff overlay.

Each node tree is serialized to a JSON file and tracked individually in Git, giving you a precise history of every change. Branch for experiments, collaborate through GitHub, and restore any version in seconds.

---

## What's New in 1.0.0

### Shader Node Support
NodeSync now tracks **Shader Nodes** alongside Geometry Nodes:
- **Standalone shader groups** — `bpy.data.node_groups` with type `SHADER` are exported to `nodes/shader/<name>.json`
- **Material shader trees** — every material's node tree is saved to `nodes/shader/materials/<name>.json`
- **World shader trees** — world lighting setups go to `nodes/shader/worlds/<name>.json`
- **Light shader trees** — light node trees go to `nodes/shader/lights/<name>.json`

Checkout, history filtering, push/pull, and branching all work across both geometry and shader trees.

### Image Texture Tracking
Enable **Track Shader Textures** in addon preferences to have NodeSync automatically copy every image referenced by a Shader Image Texture node into a `textures/` folder and commit it to Git alongside the node JSON. Works for packed images, generated images, and external file paths. This means your full shader setup — nodes *and* textures — is reproducible from a single `git clone`.

---

## What It Does

- **Commit & restore** any version of your Geometry and Shader node trees
- **Branch** to experiment without breaking your main setup
- **Push/pull** to/from GitHub for backup and collaboration
- **Visualize diffs** with a color overlay (added / modified / deleted nodes)
- **Resolve merge conflicts** when two people edit the same group
- **Filter history** by the currently viewed node tree
- **Track image textures** referenced by shader nodes (opt-in)

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
| **History** | Browse up to 300 commits with author, date, and branch info |
| **History Filter** | Show only commits that touched the currently open node tree |
| **View Diff** | Overlays the node graph with colors showing what changed vs HEAD |

**Diff colors:**
- **Green** — node was added since last commit
- **Orange** — node was modified
- **Red ghost** — node was deleted (shown as a placeholder)

### Shader Node Tracking

NodeSync automatically exports every shader tree when you commit or save your `.blend` file. The on-disk layout is:

```
nodes/
  MyGeometryGroup.json          ← standalone geometry node groups
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

### Push & Pull

- **Push ↑** — sends your commits to GitHub
- **Pull ↓** — fetches and merges from GitHub, reimports changed trees automatically
- On **merge conflicts**, a Conflicts panel appears with per-file options:
  - **Keep Mine** — use your local version
  - **Use Remote** — use the incoming version
  - **Complete Merge** / **Abort Merge** when done

### Addon Preferences

| Preference | Description |
|------------|-------------|
| **GitHub Personal Access Token** | Classic PAT with `repo` scope for push/pull |
| **Auto-Push on Commit** | Automatically push after every commit when a remote is configured |
| **Screenshot Node Editor on Commit** | Capture a screenshot of the node editor and attach it to the commit |
| **Track Shader Textures** | Copy image textures from Shader Image Texture nodes into `textures/` on commit |

---

## Known Bugs

### Node Groups Not Appearing After Checkout (Recall)

**Symptom:** You check out an older commit and some node groups don't appear in Blender, even though they exist in the JSON files for that commit.

**Root cause:** When NodeSync reconstructs node groups from JSON during checkout, Blender's internal naming system can interfere. If any node group with a similar name exists in memory (even from a previous session or a deleted modifier), Blender may auto-rename the newly created group to `GroupName.001` rather than `GroupName`. NodeSync then can't find it under the expected name, so it silently fails to attach it.

**Workaround:** Before checking out a commit, manually create an empty node group in Blender with the **exact same name** as the group you're trying to restore. Then perform the checkout. NodeSync will find the name slot already occupied by the correct identifier and reconstruct into it properly.

**Steps:**
1. Note the name of the group you expect to appear (check the commit JSON in `nodes/` if unsure)
2. In the Node editor, go **Node → New Node Group** and name it exactly as expected
3. Perform the checkout — the group should now restore correctly

---

## How It Works (Technical)

Each node tree is serialized to a JSON file containing:
- The full node interface (inputs/outputs with types, defaults, min/max)
- Every node with its type, position, properties, and socket defaults
- All links between nodes
- For embedded material/world/light trees: `owner_type` and `owner_name` tags so the deserializer knows which Blender data-block to attach to

On checkout or pull, NodeSync reconstructs every node tree from JSON in dependency order (nested groups first). Socket matching uses Blender's internal socket identifiers for stability, keeping git history clean even when sockets are reordered.

Git operations run via subprocess. No external Python dependencies required — only the standard library and Blender's `bpy`.

---

## Requirements

- Blender 4.x
- Git installed and on your PATH
- GitHub PAT with `repo` scope (for push/pull only)
