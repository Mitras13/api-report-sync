# Project knowledge graph

Official tool: https://github.com/Graphify-Labs/graphify
Version 0.9.101 is isolated in `.graphify-tool/venv`.

From the project root in PowerShell:

```powershell
.graphify-tool/venv/Scripts/python.exe scripts/graphify_project.py status
.graphify-tool/venv/Scripts/python.exe scripts/graphify_project.py update
.graphify-tool/venv/Scripts/python.exe -m graphify query "downloader retry SQL panel"
```

Update builds a local code graph without an API key and records source hashes.
Outputs live in graphify-out/: graph.json, GRAPH_REPORT.md and graph.html.
AGENTS.md requires graph-first scope analysis and a final freshness report.

Rebuild after code, SQL, imports, interfaces, routes, config, dependencies,
architecture docs or source layout changes. Excluded data/logs/tokens do not
require refresh. Documents are tracked for freshness but not semantically
indexed. SQL coverage is parser-dependent; inspect SQL and architecture docs
alongside graph results. No downloaders or live SQL queries run during build.

Recreate installation:

```powershell
python -m venv .graphify-tool/venv
.graphify-tool/venv/Scripts/python.exe -m pip install graphifyy==0.9.101
.graphify-tool/venv/Scripts/python.exe -m graphify install --project --platform codex
.graphify-tool/venv/Scripts/python.exe scripts/graphify_project.py update
```

Graph refresh and tool upgrade are separate. After a tool upgrade, reinstall
its project skill and rebuild the graph.

SQL parser is installed (`tree-sitter-sql==0.3.11`). Include that package when
recreating the environment. The refresh wrapper forces extraction to include
parser changes and regenerates the report and visualization via cluster-only.
