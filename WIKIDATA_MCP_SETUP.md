# Wikidata MCP Server Setup for Claude Code

## Overview

The official Wikidata MCP (Model Context Protocol) server provides Claude Code with direct access to Wikidata search, entity lookup, and SPARQL queries. No API key required.

- **Endpoint**: `https://wd-mcp.wmcloud.org/mcp/`
- **Documentation**: https://www.wikidata.org/wiki/Wikidata:MCP
- **API docs / test UI**: https://wd-mcp.wmcloud.org/docs
- **Transport**: HTTP (streamable)

## Setup

### 1. Add the MCP server

From the project directory, run:

```bash
claude mcp add --transport http wikidata https://wd-mcp.wmcloud.org/mcp/
```

This writes the config to `.claude.json` under the project's `mcpServers`:

```json
{
  "mcpServers": {
    "wikidata": {
      "type": "http",
      "url": "https://wd-mcp.wmcloud.org/mcp/"
    }
  }
}
```

### 2. Restart Claude Code

The MCP server is discovered at startup. After adding it, exit and restart:

```
/exit
claude
```

### 3. Allow the tools in project settings

Add to `.claude/settings.local.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__wikidata__search_items",
      "mcp__wikidata__get_statements",
      "mcp__wikidata__execute_sparql"
    ]
  }
}
```

## Available Tools

Once connected, six tools are available:

| Tool | Description |
|------|-------------|
| `mcp__wikidata__search_items(query)` | Hybrid keyword/vector search for Wikidata items |
| `mcp__wikidata__search_properties(query)` | Search for Wikidata properties |
| `mcp__wikidata__get_statements(item_id)` | Get all statements (claims) for an entity |
| `mcp__wikidata__get_statement_values(item_id, property_id)` | Get values for a specific property |
| `mcp__wikidata__get_instance_and_subclass_hierarchy(item_id)` | Get type hierarchy |
| `mcp__wikidata__execute_sparql(query)` | Run SPARQL queries against Wikidata |

## Usage Examples

### Search for a place
```
mcp__wikidata__search_items("Frontenac County Ontario")
```

### Verify an entity
```
mcp__wikidata__get_statements("Q739928")
```

### Check P31 (instance of)
```
mcp__wikidata__get_statement_values("Q739928", "P31")
```

## Comparison with Other Approaches

| Method | Rate Limits | Speed | Reliability |
|--------|-------------|-------|-------------|
| **Wikidata MCP** | Generous | Fast | Good (hosted by Wikimedia) |
| Wikidata SPARQL (`query.wikidata.org`) | Aggressive IP blocking | Fast | Fragile (403 after ~50 queries) |
| Wikidata REST API (`wbsearchentities`) | Moderate | Medium | OK but returns noisy results |
| QLever (`qlever.dev/api/wikidata`) | Generous | Fast | Good (independent mirror) |

**Recommendation**: Use MCP for interactive entity lookup (one-at-a-time). Use QLever for bulk SPARQL queries (batch operations).

## Notes

- The MCP server is hosted on Wikimedia Cloud Services (`wmcloud.org`)
- No authentication or API key is required
- The search uses hybrid keyword + vector search, so it's better than `wbsearchentities` at finding relevant results
- Previously we used a third-party MCP server (`@zzaebok/mcp-wikidata` via Smithery) but the official server is simpler and keyless
