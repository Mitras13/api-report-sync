# Project Graphify workflow

For every request about this project:
1. Run `.graphify-tool/venv/Scripts/python.exe scripts/graphify_project.py status`.
2. Query the graph before deciding scope:
   `.graphify-tool/venv/Scripts/python.exe -m graphify query "<task keywords>"`.
   Use explain/path to trace dependencies and downstream impact. State affected
   modules and checks before editing. Verify findings against current source.
3. When stale, inspect changed/new/deleted files and refresh before relying on
   affected relationships. If unavailable, disclose it and inspect sources.
4. Preserve user changes; keep edits within the task.
5. Run status at the end. In the final Persian response explicitly state whether
   the graph needs updating, why, and give the update command when necessary.

Update: `.graphify-tool/venv/Scripts/python.exe scripts/graphify_project.py update`

Refresh after code, SQL, imports, signatures, routes, config, requirements,
architecture docs or source file layout changes. Excluded data/logs/tokens do
not require refresh. Content hashes include uncommitted source files.

Coverage: local code AST graph. Documents are freshness-tracked but not
semantically indexed. Read README.md and relevant CLAUDE.md sections for context.
SQL coverage is parser-dependent; inspect SQL sources for database tasks.
Source remains authoritative. Use the isolated Graphify interpreter above.
See GRAPHIFY.md for setup and usage.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.

## Local installation overrides
Use `.graphify-tool/venv/Scripts/python.exe -m graphify` wherever the generated
section above says bare `graphify` (it is not on global PATH). After changes,
use `scripts/graphify_project.py update` with that interpreter instead of bare
`graphify update .`, so source hashes, report and HTML are refreshed together.
Inspect source freely where the graph is stale, incomplete or misses a symbol.
