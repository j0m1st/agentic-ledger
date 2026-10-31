# Connecting your agent to the books

**Default path:**

| System | Default | Why |
|---|---|---|
| QuickBooks Online | **Connector (MCP)** | First-party connector, OAuth in the browser, no developer app |
| Xero | **Connector (MCP)** | Official Xero MCP server, one Custom Connection |
| Sage Intacct | **Direct API** | Multi-entity and dimensions need full queries; the Sage MCP gateway is read-only and admin-enabled |
| NetSuite | **Direct API** | SuiteQL gives the complete GL in bulk; MCP tools are slower and capped per call |

Both paths work for every system. The API path also unlocks `python -m engine run` (bulk extract, normalize, profile).

> Verified against vendor docs and announcements as of Oct 2026. Vendors change menus often: if a step doesn't match, follow the linked vendor doc.

## Rules for every path

- **Least privilege.** Use a dedicated integration user/role with *view-only* permissions. Where scopes exist, pick `.read` scopes.
- **Secrets in the OS keychain**, not in files. `python -m engine auth <book>` prompts for secrets (hidden input) and stores them via `keyring` (macOS Keychain, Windows Credential Manager, Linux Secret Service). For CI or 1Password, use env vars `AL_<BOOK>_<KEY>` (for example `op run --env-file=...`).
- **Never paste secrets into the agent chat** or into `claude mcp add ... --env KEY=secret`, which stores them in plaintext config. Use `python -m engine exec <book> -- <command>` to inject them from the keychain at runtime (examples below).
- **Sandbox first** when the vendor offers one (QBO sandbox, Xero demo company, NetSuite sandbox account).
- **Rotate** any secret that has touched a terminal history, a screenshot or a chat.

## How each agent adds an MCP server

| Agent | Remote (HTTP + OAuth) | Local (stdio) |
|---|---|---|
| Claude Code | `claude mcp add --transport http <name> <url>`, then `/mcp` to sign in. Connectors added at claude.ai (Settings › Connectors) also show up in Claude Code. | `claude mcp add <name> -- <command>` |
| Codex CLI | `codex mcp add <name> --url <url>`, then `codex mcp login <name>` | `codex mcp add <name> -- <command>` |
| Cursor | `.cursor/mcp.json`: `{"mcpServers":{"<name>":{"url":"<url>"}}}` | `{"mcpServers":{"<name>":{"command":"...","args":[...]}}}` |

Add `--scope project` (Claude Code) only if the config contains no secrets. These examples never put secrets in config.

---

## QuickBooks Online

### A. Connector (default)
1. **Claude:** claude.ai › Settings › Connectors › Browse › **Intuit QuickBooks** › Connect, then sign in to Intuit and pick the company. It appears in Claude Code automatically when you're signed in with the same claude.ai account (check with `/mcp`). The connector is US-only at present.
2. **Other agents, or no claude.ai account:** use Intuit's open-source local server [intuit/quickbooks-online-mcp-server](https://github.com/intuit/quickbooks-online-mcp-server). It needs a developer app (steps B1–B3), then:
   ```bash
   claude mcp add qbo -- python -m engine exec acme -- npx -y <package-or-path-from-intuit-README>
   ```
   `engine exec` injects `QUICKBOOKS_CLIENT_ID/SECRET/REFRESH_TOKEN/REALM_ID/ENVIRONMENT`. Check the env names against the Intuit README. Caveat: if the server rotates the refresh token itself, re-run `engine auth`.
3. The connector can write. The agent rules forbid writes, but review the connector's permission prompt and deny write tools if your client supports per-tool approval.

### B. Direct API
1. [developer.intuit.com](https://developer.intuit.com) › Dashboard › Create app › QuickBooks Online and Payments. Scope: `com.intuit.quickbooks.accounting`. This scope is read+write and there's no read-only option, so the engine enforces read-only in code.
2. **Keys & credentials:** Development keys work against the sandbox. Production keys require completing Intuit's app profile/compliance questions.
3. **Redirect URI:** sandbox can use `http://localhost:8080/callback`. Production must be HTTPS. Any HTTPS URL you control works, because you only copy the redirected URL from the browser bar. Intuit's playground URL `https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl` also works.
4. `python -m engine new acme --erp qbo && python -m engine auth acme`. It prints a consent URL; you approve, then paste the redirected URL back. The realm ID and refresh token are stored in the keychain.
5. Tokens: the access token lasts 1 h. The refresh token **rotates on every refresh** (the engine saves the new one automatically) and has a hard 5-year cap ([Intuit policy](https://developers.intuit.com/app/developer/qbo/docs/release-notes/general-release-notes)).

## Xero

### A. Connector (default)
Official server: [XeroAPI/xero-mcp-server](https://github.com/XeroAPI/xero-mcp-server) (stdio, Node 18+).
1. [developer.xero.com](https://developer.xero.com/app/manage) › New app › **Custom connection**. This is a paid Xero add-on, tied to one organisation, and region-limited, so check eligibility. Select **read-only scopes only**. Connections created on or after 29 Apr 2026 use the new granular scopes. Authorise it as an org admin.
2. `python -m engine new acme --erp xero && python -m engine auth acme` stores the client ID and secret in the keychain and tests the token.
3. Register the server without writing secrets to config:
   ```bash
   claude mcp add xero -- python -m engine exec acme -- npx -y @xeroapi/xero-mcp-server@latest
   ```
   The server exposes create/update/delete tools, so read-only scopes are your real guardrail.

### B. Direct API
The Custom Connection from A1 doubles as the API credential (OAuth2 `client_credentials` at `https://identity.xero.com/connect/token`, no browser step, no tenant header). Run `python -m engine run acme`. Include `accounting.journals.read` in the connection's scopes; the full GL comes from `/Journals`. Rate limits are 60 calls/min and 5,000/day, and the engine backs off automatically.

## Sage Intacct

### A. Direct API (default)
1. **Developer app:** [developer.sage.com/intacct](https://developer.sage.com/intacct) › register an application to get a client ID and secret.
2. **In the company:** an admin authorises the app for the company (Web Services authorizations / application subscription) and creates a dedicated **Web Services user** with a read-only role covering GL, AR, AP, Company/Dimensions. Multi-entity: give the user access to the top level.
3. `python -m engine new acme --erp intacct && python -m engine auth acme` prompts for client ID/secret, company ID and the WS user ID. It uses the OAuth2 `client_credentials` grant at `https://api.intacct.com/ia/api/v1/oauth2/token` with `username = <userId>@<companyId>`. If the token call is rejected, check the username format in Sage's [OAuth 2.0 guide](https://developer.sage.com/intacct/docs/developer-portal/guides/oauth2).

### B. Connector
**Sage Intacct AI Gateway** is Sage's first-party, **read-only** MCP server on top of the REST API, generally available since 2026. An admin enables it, after which you add its endpoint URL in your agent (remote HTTP, table above). It's good for Q&A. Use the API for the full reverse-engineering extract. Third-party alternative: CData's Intacct MCP.

## NetSuite

### A. Direct API (default): OAuth 2.0 machine-to-machine
1. **Enable features:** Setup › Company › Enable Features › SuiteCloud: *REST Web Services*, *OAuth 2.0*.
2. **Role:** a custom role (not Administrator) with view-level Lists/Transactions/Reports, *Perform Search*, *REST Web Services*, *Log in using OAuth 2.0 Access Tokens*, and *SuiteAnalytics Workbook*. Assign it to an integration user.
3. **Integration record:** Setup › Integration › Manage Integrations › New. Check **Client Credentials (Machine to Machine) Grant** and scope **REST Web Services**. Uncheck TBA and Authorization Code. Save the **Client ID**; M2M doesn't use the secret.
4. **Key pair**, generated locally:
   ```bash
   openssl req -new -x509 -newkey rsa:3072 -nodes -days 730 -sha256 -keyout ns_private.pem -out ns_public.pem -subj "/CN=agentic-ledger"
   ```
5. Setup › Integration › Manage Authentication › **OAuth 2.0 Client Credentials (M2M) Setup** › Create New: choose the user, role and application, and upload `ns_public.pem`. Copy the **Certificate ID**.
6. `python -m engine new acme --erp netsuite && python -m engine auth acme` asks for the account ID (e.g. `1234567` or `1234567_SB1`), client ID, certificate ID and the private key path. The key is stored in the keychain. **Then delete `ns_private.pem`.** Tokens are PS256-signed JWT assertions, valid 60 min, with no refresh token. Certificates last at most 2 years, so put renewal on your calendar.

### B. Connector
**NetSuite AI Connector Service** (2025.2+):
1. Install the **MCP Standard Tools** SuiteApp (SuiteApp Marketplace).
2. Create a custom role (Administrator is blocked) with *MCP Server Connection*, *OAuth 2.0 Access Tokens* and the view permissions above.
3. Claude: Settings › Connectors › add **NetSuite**, or add a custom connector with the account's MCP URL (`https://<accountid>.suitetalk.api.netsuite.com/services/mcp/v1/all`, account ID lowercase with `_` → `-`; confirm in NetSuite Help › "AI Connector Service"). Claude Code: `claude mcp add --transport http netsuite <url>`, then `/mcp` to sign in.
4. Tools run under that role's permissions. Keep the role view-only.

---

## Verify the connection

- **API:** `python -m engine extract acme --start 2025-01-01 --end 2025-01-31`, then check `books/acme/raw/_manifest.json` for errors.
- **MCP:** ask the agent to "list the chart of accounts". It should return real account names.
