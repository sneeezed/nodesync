# NodeSync

**NodeSync** is a Blender addon that brings Git-based version control to Geometry Node groups. It lets you commit, branch, push, pull, and restore your node setups just like you would source code — with full GitHub integration and a live diff overlay.

Each node group is serialized to a JSON file and tracked individually in Git, so you get a precise history of every change, can branch for experiments, and collaborate with teammates through GitHub.

---

## What It Does

- **Commit & restore** any version of your Geometry Node groups
- **Branch** to experiment without breaking your main setup
- **Push/pull** to/from GitHub for backup and collaboration
- **Visualize diffs** with a color overlay (added / modified / deleted nodes)
- **Resolve merge conflicts** when two people edit the same group
- **Filter history** by node group to see only relevant commits

---

## Installation

1. Download or build `nodesync.zip`
2. In Blender: **Edit → Preferences → Add-ons → Install** → select `nodesync.zip`
3. Enable the addon

The NodeSync panel appears in the **Geometry Node Editor → N-panel → NodeSync tab**.

---

## Getting Started

### Initialize a New Project

1. Open the NodeSync panel in the Geometry Node editor
2. Set your **Project Root** folder (defaults to the `.blend` file directory)
3. Click **Init New Project** — this creates a `nodes/` folder, a `.nodesync` config file, and runs `git init`

### Make Your First Commit

1. Type a message in the **Commit message** field
2. Click **Commit** — all Geometry Node groups are serialized to `nodes/GroupName.json` and committed

### Connect to GitHub (Optional)

1. Create an empty repo on GitHub
2. Paste the repo URL into the **Remote URL** field and click **Set Remote**
3. Add your GitHub Personal Access Token (PAT) in **Edit → Preferences → Add-ons → NodeSync**
4. Click **Push ↑** to upload

### Clone an Existing Project

1. Paste the GitHub URL and choose a local folder
2. Click **Clone from GitHub** — all node groups are imported automatically

---

## Features

### Version Control

| Action | Description |
|--------|-------------|
| **Commit** | Saves all node groups to JSON and creates a Git commit |
| **Checkout** | Restores your node groups to any previous commit |
| **History** | Browse up to 300 commits with author, date, and branch info |
| **History Filter** | Show only commits that touched the currently open node group |
| **View Diff** | Overlays your node graph with colors showing what changed vs HEAD |

**Diff colors:**
- **Green** — node was added since last commit
- **Orange** — node was modified
- **Red ghost** — node was deleted (shown as a placeholder)

### Branching

- **Create Branch** from the Branches panel
- **Switch Branch** — reimports all node groups from the target branch
- Each branch gets a unique color swatch shown in the history list

### Push & Pull

- **Push ↑** — sends your commits to GitHub
- **Pull ↓** — fetches and merges from GitHub, reimports changed groups automatically
- On **merge conflicts**, a Conflicts panel appears with per-file options:
  - **Keep Mine** — use your local version
  - **Use Remote** — use the incoming version
  - **Complete Merge** / **Abort Merge** when done

---

## Known Bugs

### Node Groups Not Appearing After Checkout (Recall)

**Symptom:** You check out an older commit and some node groups don't appear in Blender, even though they exist in the JSON files for that commit.

**Root cause:** When NodeSync reconstructs node groups from JSON during checkout, Blender's internal naming system can interfere. If any node group with a similar name exists in memory (even from a previous session or a deleted modifier), Blender may auto-rename the newly created group to `GroupName.001` rather than `GroupName`. NodeSync then can't find it under the expected name, so it silently fails to attach it.

**Workaround:** Before recalling (checking out) a commit, manually create an empty Geometry Node group in Blender with the **exact same name** as the group you're trying to restore. Then perform the checkout. NodeSync will find the name slot already occupied by the correct identifier and reconstruct into it properly.

**Steps:**
1. Note the name of the group you expect to appear (check the commit JSON in `nodes/` if unsure)
2. In the Geometry Node editor, go **Node → New Node Group** and name it exactly as expected
3. Perform the checkout — the group should now restore correctly

A proper fix is tracked for a future release (see Roadmap).

---

## Roadmap

NodeSync currently targets **Geometry Nodes**. The architecture is built to expand, and the serialization system already handles the majority of node types. Planned expansions:

### Near Term
- **Fix the checkout naming bug** — read the actual group name from JSON content instead of deriving it from the filename, eliminating the mismatch between sanitized filenames and real Blender node group names
- **Shader Node Groups** — version control for material node setups (very similar architecture, mainly a different node tree type)

### Medium Term
- **Compositor Node Groups** — track compositing setups alongside geometry nodes
- **Per-group commit** — commit individual groups rather than all at once
- **Commit screenshots** — visual thumbnails alongside history entries (groundwork already exists in the addon)

### Longer Term
- **Light Tree / World Node Groups** — extend coverage to remaining node editor types
- **Selective checkout** — restore individual groups from any commit without affecting others
- **Conflict merge stuff** — Right now merge conflicts are not really able to be resolved

---

## How It Works (Technical)

Each Geometry Node group is serialized to a JSON file (`nodes/GroupName.json`) containing:
- The full node interface (inputs/outputs with types, defaults, min/max)
- Every node with its type, position, properties, and socket defaults
- All links between nodes

On checkout or pull, NodeSync reconstructs every node group from JSON in dependency order (nested groups first). Socket matching uses Blender's internal socket identifiers for stability, so git history stays clean even when sockets are reordered.

Git operations run via subprocess. No external Python dependencies required — only the standard library and Blender's `bpy`.

---

## Requirements

- Blender 4.x
- Git installed and on your PATH
- GitHub PAT with `repo` scope (for push/pull only)
