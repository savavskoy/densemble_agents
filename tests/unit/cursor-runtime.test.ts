import { randomUUID } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LoadedConfig } from "../../src/config/index.js";
import type { RunIdentity, RuntimeEvent, Session } from "../../src/domain.js";
import { createCursorRuntime, cursorAgentId, cursorSandboxPolicyActive, cursorStoredAgentCwd, type CursorAgentHandle, type CursorGateway, type CursorRunHandle, type CursorSessionSpec } from "../../src/agents/cursor.js";
import { DeletionJournal } from "../../src/application/deletion.js";
import type { ControlledRuntime } from "../../src/agents/contracts.js";
import { scope, until } from "./session-runtime-fixtures.js";

const roots: string[] = [];
const runtimes: ControlledRuntime[] = [];
afterEach(async () => {
  for (const runtime of runtimes.splice(0)) await runtime.shutdown();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function setup() {
  const root = resolve(".cache", `cursor-unit-${randomUUID()}`);
  roots.push(root);
  const workspace = join(root, "workspace");
  const home = join(root, "cursor-home");
  mkdirSync(workspace, { recursive: true });
  mkdirSync(home, { recursive: true });
  writeFileSync(join(workspace, "AGENT.md"), "Synthetic persona instructions.");
  writeFileSync(join(workspace, "AGENTS.md"), "Synthetic workspace rules.");
  const config: LoadedConfig = {
    config: {
      workspacePath: workspace, agentDefinitionsPath: workspace, agentLaunchersPath: workspace,
      secretsPath: join(root, "secrets.local.json"), runtimeDataPath: root, runtimeHomePath: join(root, "copilot"),
      skillDirectories: [workspace], ownerId: scope.ownerId, permissionMode: "autopilot",
      cursor: { homePath: home, defaultModel: "grok-4.7" },
      bots: [{ id: scope.botId, agentId: "synthetic-agent", tokenRef: "bot.token", engine: "cursor" }],
      bindings: [{ botId: scope.botId, chatId: scope.chatId, topicId: null, kind: "private" }], mcp: { mode: "none" },
    },
    agents: [
      { id: "synthetic-agent", defaultModel: "copilot-model", description: "Persona", userInvocable: true,
        canonicalPath: join(workspace, "AGENT.md"), launcherPath: join(workspace, "AGENT.md") },
    ],
    resolveSecret: () => "known-secret", tokenForBot: () => "123456:synthetic",
  };
  const session: Session = {
    id: randomUUID(), conversationId: randomUUID(), scope, agentId: "synthetic-agent", engine: "cursor", workspace,
    providerSessionId: null, appliedModel: "grok-4.7", pendingModel: null, generation: 1, createdAt: 0, updatedAt: 0,
  };
  const opened: CursorSessionSpec[] = [];
  const sent: string[] = [];
  let settle: (result: { status: "finished" | "cancelled"; result?: string }) => void = () => undefined;
  const gateway: CursorGateway = {
    authenticated: async () => true,
    models: async () => ({ models: [{ id: "grok-4.7", name: "Grok 4.7", supportsImages: true }], accepted: new Set(["grok-4.7"]) }),
    open: async (spec) => {
      opened.push(spec);
      const handle: CursorAgentHandle = {
        agentId: "agent-synthetic",
        send: async (input, hooks) => {
          sent.push(input.text);
          hooks.onText("Partial");
          let settled = false;
          const current: CursorRunHandle = {
            wait: () => new Promise((done) => { settle = (result) => { if (!settled) { settled = true; done(result); } }; }),
            cancel: async () => settle({ status: "cancelled" }),
            steer: async () => "complete_delivered",
          };
          return current;
        },
        close: async () => settle({ status: "cancelled" }),
      };
      return handle;
    },
    remove: vi.fn(async () => undefined),
  };
  const events: RuntimeEvent[] = [];
  const runtime = createCursorRuntime({ config, diagnostics: { record: vi.fn() }, gateway, previewIntervalMs: 0 });
  runtimes.push(runtime);
  const identity: RunIdentity = { scope, sessionId: session.id, runId: randomUUID(), generation: 1 };
  return { config, runtime, session, identity, opened, sent, events, gateway, finish: () => settle({ status: "finished", result: "Done" }) };
}

describe("cursor runtime", () => {
  it("opens a local owner session without a sandbox and streams the reply", async () => {
    const f = setup();
    const opened = await f.runtime.open({ session: f.session, onEvent: (event) => f.events.push(event), emptyHistory: true });
    expect(opened.providerSessionId).toBe("agent-synthetic");
    expect(cursorAgentId.test(opened.providerSessionId)).toBe(true);
    expect(f.opened[0]).toMatchObject({ cwd: f.session.workspace, sandbox: false, model: "grok-4.7" });
    await f.runtime.execute({ kind: "send", identity: f.identity, input: { text: "Hello", images: [], attachmentIds: [], notices: [] } });
    expect(f.sent[0]).toContain("Synthetic persona instructions.");
    expect(f.sent[0]).toContain("# User message\nHello");
    expect(f.events.map((event) => event.kind)).toContain("delta");
    f.finish();
    await until(() => f.events.some((event) => event.kind === "completed"));
    expect(f.events.map((event) => event.kind)).toEqual(["delta", "completed"]);
  });

  it("keeps the persona preface off follow-up turns and accepts a steer", async () => {
    const f = setup();
    await f.runtime.open({ session: f.session, onEvent: (event) => f.events.push(event), emptyHistory: true });
    await f.runtime.execute({ kind: "send", identity: f.identity, input: { text: "Hello", images: [], attachmentIds: [], notices: [] } });
    f.finish();
    await until(() => f.events.some((event) => event.kind === "completed"));
    const followUp: RunIdentity = { ...f.identity, runId: randomUUID() };
    await f.runtime.execute({ kind: "send", identity: followUp, input: { text: "Again", images: [], attachmentIds: [], notices: [] } });
    expect(f.sent[1]).toBe("Again");
    await expect(f.runtime.execute({ kind: "steer", identity: followUp, input: { text: "Also this", images: [], attachmentIds: [], notices: [] } })).resolves.toBeUndefined();
    f.finish();
  });

  it("refuses a session that belongs to another engine", async () => {
    const f = setup();
    await expect(f.runtime.open({ session: { ...f.session, engine: "copilot" }, onEvent: () => undefined }))
      .rejects.toThrow("SESSION_ENGINE_MISMATCH");
  });

  it("refuses Cursor while MCP is allowlisted, because the SDK cannot limit that server's tools", async () => {
    const f = setup();
    f.config.config.mcp = { mode: "allowlist", servers: [{ name: "notes", type: "stdio", command: "notes", args: [], env: {}, tools: ["read"] }] };
    await expect(f.runtime.open({ session: f.session, onEvent: () => undefined, emptyHistory: true }))
      .rejects.toThrow("MCP_TOOL_ALLOWLIST_REQUIRED");
    expect(f.opened).toHaveLength(0);
  });

  it("deletes a closed session by agent id, without guessing the workspace", async () => {
    const f = setup();
    await f.runtime.open({ session: f.session, onEvent: () => undefined, emptyHistory: true });
    await f.runtime.disconnect(f.session.scope, f.session.id);
    await f.runtime.deleteSession(f.session.scope, f.session.id, "agent-synthetic");
    expect(f.gateway.remove).toHaveBeenCalledWith("agent-synthetic");
  });

  it("sandboxes a guest and refuses one when a personal Cursor sandbox policy is present", async () => {
    const f = setup();
    const guestWorkspace = join(f.config.config.runtimeDataPath, "guest");
    mkdirSync(guestWorkspace, { recursive: true });
    const guest = { ...scope, ownerId: 202, chatId: 202 };
    f.config.config.users = [{ telegramUserId: guest.ownerId, allowedBotIds: [scope.botId] }];
    f.config.config.workspaces = [{
      id: "guest", name: "Guest", access: "private", ownerUserId: guest.ownerId,
      path: guestWorkspace, agentIds: ["synthetic-agent"],
    }];
    const session = { ...f.session, id: randomUUID(), scope: guest, workspace: guestWorkspace };
    const clear = join(f.config.config.runtimeDataPath, "sandbox-clear.json");
    const active = join(f.config.config.runtimeDataPath, "sandbox-active.json");
    writeFileSync(clear, JSON.stringify({ type: "insecure_none" }));
    writeFileSync(active, JSON.stringify({ type: "workspace_readwrite" }));
    const openGuest = (sandboxPolicyPath: string) => createCursorRuntime({
      config: f.config, diagnostics: { record: vi.fn() }, gateway: f.gateway, previewIntervalMs: 0, sandboxPolicyPath,
    });
    const allowed = openGuest(clear);
    runtimes.push(allowed);
    const opened = await allowed.open({ session, onEvent: () => undefined, emptyHistory: true });
    expect(opened.providerSessionId).toBe("agent-synthetic");
    expect(f.opened.at(-1)).toMatchObject({ sandbox: true, cwd: guestWorkspace });
    const blocked = openGuest(active);
    runtimes.push(blocked);
    await expect(blocked.open({ session: { ...session, id: randomUUID() }, onEvent: () => undefined, emptyHistory: true }))
      .rejects.toThrow("CURSOR_SANDBOX_POLICY_CONFLICT");
  });

  it("treats only insecure_none as an inactive personal sandbox policy", () => {
    expect(cursorSandboxPolicyActive({ type: "insecure_none" })).toBe(false);
    expect(cursorSandboxPolicyActive({ type: "workspace_readwrite" })).toBe(true);
    expect(cursorSandboxPolicyActive({})).toBe(true);
    expect(cursorSandboxPolicyActive(null)).toBe(true);
  });

  it("resolves a stored cursor agent cwd from any workspace", async () => {
    const root = resolve(".cache", `cursor-store-${randomUUID()}`);
    roots.push(root);
    mkdirSync(root, { recursive: true });
    const { JsonlLocalAgentStore } = await import("@cursor/sdk");
    const store = new JsonlLocalAgentStore(join(root, "agents"));
    const cwd = join(root, "other-workspace");
    await store.agents.create({ agent: {
      agentId: "agent-synthetic", cwd, status: "idle", createdAt: 1, updatedAt: 1,
    } });
    await expect(cursorStoredAgentCwd(store, "agent-synthetic")).resolves.toBe(cwd);
    await expect(cursorStoredAgentCwd(store, "agent-missing")).resolves.toBeUndefined();
    await expect(cursorStoredAgentCwd(store, "bc-cloud")).rejects.toThrow("UNOWNED_PROVIDER_SESSION");
  });

  it("accepts only a local Cursor agent id in the deletion journal", async () => {
    const root = resolve(".cache", `cursor-journal-${randomUUID()}`);
    roots.push(root);
    mkdirSync(root, { recursive: true });
    const journal = new DeletionJournal(root);
    const intent = { scope, sessionId: randomUUID(), providerSessionId: "agent-synthetic", artifacts: [], engine: "cursor" as const };
    await journal.save(intent);
    expect((await journal.pending())[0]?.providerSessionId).toBe("agent-synthetic");
    await expect(journal.save({ ...intent, sessionId: randomUUID(), providerSessionId: `densemble-${intent.sessionId}` }))
      .rejects.toThrow("DELETION_JOURNAL_INVALID");
  });
});
