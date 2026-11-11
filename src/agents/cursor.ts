import { mkdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, relative } from "node:path";
import type { InteractionUpdate, McpServerConfig, SDKCustomTool, SDKJsonValue } from "@cursor/sdk";
import { z } from "zod";
import { authorizedWorkspace, DEFAULT_WORKSPACE_ID, linkedWorkspaces, ownerLabel, type AgentDefinition, type LoadedConfig } from "../config/index.js";
import type { ModelInfo, RunIdentity, RuntimeCommand, RuntimeEvent, Scope, Session } from "../domain.js";
import { scopeKey } from "../domain.js";
import type { DiagnosticSink } from "../ports.js";
import type { ControlledRuntime, ControlledSessionOptions, ProactivityRequest } from "./contracts.js";
import { bounded, RuntimeError } from "./contracts.js";
import { proactivityRequestSchema } from "./copilot.js";
import { workspaceInstructions } from "./claude-env.js";
import { linkedWorkspacesInstruction } from "./workspace-guard.js";
import { abilityParameters, invokeGuarded, type ModuleToolGuard } from "./module-tools.js";
import type { ModuleHost } from "../modules/host.js";
import { buildSessionModules } from "../modules/instructions.js";

/** Local Cursor agent ids. Cloud ids (`bc-`) are never accepted: knowledge stays on this machine. */
export const cursorAgentId = /^agent-[A-Za-z0-9_-]+$/;
const imageTypes = new Set(["image/png", "image/jpeg", "image/webp"]);

export function cursorHome(config: LoadedConfig): string {
  const home = config.config.cursor?.homePath;
  if (!home) throw new RuntimeError("CURSOR_NOT_CONFIGURED");
  return home;
}

/**
 * True when a parsed `~/.cursor/sandbox.json` would become the SDK's personal sandbox policy.
 * `insecure_none` is the only shape the SDK ignores. Anything else, including a foreign shape, is active.
 */
export function cursorSandboxPolicyActive(parsed: unknown): boolean {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return true;
  return (parsed as { type?: unknown }).type !== "insecure_none";
}

/** Refuses a guest run when the SDK would apply the interactive user's sandbox policy. A missing file is fine. */
export async function assertCursorGuestSandbox(policyPath = join(homedir(), ".cursor", "sandbox.json")): Promise<void> {
  let text: string;
  try {
    text = await readFile(policyPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw new RuntimeError("CURSOR_SANDBOX_POLICY_CONFLICT");
  }
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch { throw new RuntimeError("CURSOR_SANDBOX_POLICY_CONFLICT"); }
  if (cursorSandboxPolicyActive(parsed)) throw new RuntimeError("CURSOR_SANDBOX_POLICY_CONFLICT");
}

/** Cwd stored for this local agent, independent of the workspace the caller still has. Missing means already deleted. */
export async function cursorStoredAgentCwd(
  store: { agents: { get(input: { agentId: string }): Promise<{ agentId: string; cwd: string } | null> } },
  agentId: string,
): Promise<string | undefined> {
  if (!cursorAgentId.test(agentId)) throw new RuntimeError("UNOWNED_PROVIDER_SESSION");
  const saved = await store.agents.get({ agentId });
  if (!saved || saved.agentId !== agentId) return undefined;
  return saved.cwd;
}

export interface CursorTool {
  description: string;
  inputSchema?: Record<string, unknown>;
  execute(args: Record<string, unknown>): Promise<unknown>;
}
export interface CursorRunHandle {
  wait(): Promise<{ status: "finished" | "error" | "cancelled"; result?: string; errorCode?: string; errorMessage?: string }>;
  cancel(): Promise<void>;
  steer?(text: string): Promise<"complete_delivered" | "revert_to_followup">;
}
export interface CursorAgentHandle {
  agentId: string;
  send(input: { text: string; images: { data: string; mimeType: string }[] }, hooks: {
    model: string; onText: (chunk: string) => void;
  }): Promise<CursorRunHandle>;
  close(): Promise<void>;
}
export interface CursorSessionSpec {
  resumeId?: string;
  cwd: string;
  dirs: string[];
  model: string;
  sandbox: boolean;
  agents: Record<string, { description: string; prompt: string }>;
  tools: Record<string, CursorTool>;
  mcp?: Record<string, McpServerConfig>;
}
export interface CursorCatalog { models: ModelInfo[]; accepted: ReadonlySet<string> }
export interface CursorGateway {
  authenticated(): Promise<boolean>;
  models(): Promise<CursorCatalog>;
  open(spec: CursorSessionSpec): Promise<CursorAgentHandle>;
  remove(agentId: string): Promise<void>;
}

interface Slot {
  scope: Scope;
  sessionId: string;
  agent?: CursorAgentHandle;
  preface: string;
  introduced: boolean;
  /** Model the next send must use. `/model` updates it without opening a new agent. */
  model?: string;
  options?: ControlledSessionOptions;
  opening?: Promise<{ providerSessionId: string }>;
  closed?: Promise<void>;
  turn?: Turn;
  closing: boolean;
  switching: boolean;
}
interface Turn {
  identity: RunIdentity;
  controller: AbortController;
  preview: string;
  lastPreview: number;
  terminal: boolean;
  cancelling: boolean;
  run?: CursorRunHandle;
}
export interface CursorRuntimeOptions {
  config: LoadedConfig;
  diagnostics: DiagnosticSink;
  modules?: ModuleHost;
  gateway?: CursorGateway;
  abortGraceMs?: number;
  previewIntervalMs?: number;
  /** Guest sandbox check. Defaults to ~/.cursor/sandbox.json. */
  sandboxPolicyPath?: string;
}

function userLabel(displayName: string | undefined): string {
  const name = displayName?.replace(/\s+/g, " ").trim();
  return name ? `${name} (a configured user)` : "a user";
}
function jsonSchema(schema: z.ZodType): Record<string, unknown> {
  const { $schema: _schema, ...rest } = z.toJSONSchema(schema, { unrepresentable: "any" }) as Record<string, unknown>;
  return rest;
}
function failureFrom(result: { errorCode?: string; errorMessage?: string }): string {
  const code = result.errorCode ?? "";
  const message = result.errorMessage ?? "";
  if (code === "rate_limit" || /usage|rate limit/i.test(message)) return "CURSOR_USAGE_LIMIT";
  if (/unauthenticated|invalid api key|authentication/i.test(message)) return "CURSOR_LOGIN_REQUIRED";
  return "CURSOR_SERVICE_ERROR";
}

/**
 * Service-owned Cursor login and local agent store. The API key comes from `cursor.homePath`, never from
 * `CURSOR_API_KEY`. A sandboxed guest is refused when `~/.cursor/sandbox.json` holds a personal policy,
 * because the SDK would apply that policy instead of the workspace sandbox.
 */
export async function createCursorGateway(config: LoadedConfig): Promise<CursorGateway> {
  const home = cursorHome(config);
  const sdk = await import("@cursor/sdk");
  const credentials = new sdk.FileCredentialStore(join(home, "auth.json"));
  const store = new sdk.JsonlLocalAgentStore(join(home, "agents"));
  async function apiKey(): Promise<string | undefined> {
    const saved = await credentials.load();
    if (!saved?.apiKey) return undefined;
    if (saved.apiKeyExpiresAtMs !== undefined && saved.apiKeyExpiresAtMs <= Date.now()) return undefined;
    return saved.apiKey;
  }
  function localOptions(spec: CursorSessionSpec): {
    cwd: string; dirs?: string[]; store: typeof store; settingSources: []; sandboxOptions: { enabled: boolean };
    customTools: Record<string, SDKCustomTool>; enableAgentRetries: false;
  } {
    const customTools: Record<string, SDKCustomTool> = {};
    for (const [name, tool] of Object.entries(spec.tools)) {
      customTools[name] = {
        description: tool.description,
        ...(tool.inputSchema ? { inputSchema: tool.inputSchema as Record<string, SDKJsonValue> } : {}),
        execute: async (args) => {
          const value = await tool.execute(args);
          return typeof value === "string" ? value : JSON.stringify(value);
        },
      };
    }
    return {
      cwd: spec.cwd, store, enableAgentRetries: false, customTools,
      // "project" would load <workspace>/.cursor/hooks.json and project MCP onto the host, outside the sandbox.
      settingSources: [],
      // `enabled: false` keeps an owner's personal ~/.cursor/sandbox.json from changing the run.
      sandboxOptions: { enabled: spec.sandbox },
      ...(spec.dirs.length ? { dirs: spec.dirs } : {}),
    };
  }
  return {
    async authenticated() { return Boolean(await apiKey()); },
    async models() {
      const key = await apiKey();
      if (!key) throw new RuntimeError("CURSOR_LOGIN_REQUIRED");
      const listed = await sdk.Cursor.models.list({ apiKey: key });
      const accepted = new Set<string>();
      const models = listed.map((model) => {
        accepted.add(model.id);
        for (const alias of model.aliases ?? []) accepted.add(alias);
        return { id: model.id, name: model.displayName, supportsImages: true };
      });
      return { models, accepted };
    },
    async open(spec) {
      const key = await apiKey();
      if (!key) throw new RuntimeError("CURSOR_LOGIN_REQUIRED");
      if (spec.mcp) throw new RuntimeError("MCP_TOOL_ALLOWLIST_REQUIRED");
      if (spec.sandbox) await assertCursorGuestSandbox();
      await mkdir(join(home, "agents"), { recursive: true, mode: 0o700 });
      const options = {
        apiKey: key, model: { id: spec.model }, local: localOptions(spec),
        // Headless runs have no approval callback. Asking is a normal chat reply, matching both existing engines.
        disallowedTools: ["askQuestion" as const],
        ...(Object.keys(spec.agents).length ? { agents: spec.agents } : {}),
      };
      let agent;
      try {
        agent = spec.resumeId ? await sdk.Agent.resume(spec.resumeId, options) : await sdk.Agent.create(options);
      } catch (error) {
        const name = error instanceof Error ? error.name : "";
        if (name === "AuthenticationError") throw new RuntimeError("CURSOR_LOGIN_REQUIRED");
        if (name === "RateLimitError") throw new RuntimeError("CURSOR_USAGE_LIMIT");
        if (spec.resumeId && name === "AgentNotFoundError") throw new RuntimeError("SESSION_HISTORY_MISSING");
        throw new RuntimeError("CURSOR_ENGINE_UNAVAILABLE");
      }
      if (!cursorAgentId.test(agent.agentId)) throw new RuntimeError("CURSOR_ENGINE_UNAVAILABLE");
      return {
        agentId: agent.agentId,
        async send(input, hooks) {
          const run = await agent.send(
            { text: input.text, ...(input.images.length ? { images: input.images } : {}) },
            {
              model: { id: hooks.model },
              onDelta: ({ update }: { update: InteractionUpdate }) => {
                if (update.type === "text-delta") hooks.onText(update.text);
              },
            },
          );
          return {
            async wait() {
              const result = await run.wait();
              return { status: result.status, ...(result.result !== undefined ? { result: result.result } : {}),
                ...(result.error?.code !== undefined ? { errorCode: result.error.code } : {}),
                ...(result.error?.message !== undefined ? { errorMessage: result.error.message } : {}) };
            },
            cancel: () => run.cancel(),
            ...(run.steer ? { steer: (text: string) => run.steer!(text) } : {}),
          };
        },
        close: () => agent[Symbol.asyncDispose](),
      };
    },
    async remove(agentId) {
      const cwd = await cursorStoredAgentCwd(store, agentId);
      if (!cwd) return;
      const key = await apiKey();
      if (!key) throw new RuntimeError("CURSOR_LOGIN_REQUIRED");
      await sdk.Agent.delete(agentId, { apiKey: key, cwd, store });
    },
  };
}

export function createCursorRuntime(options: CursorRuntimeOptions): ControlledRuntime {
  const { config, diagnostics } = options;
  const gatewayPromise = options.gateway ? Promise.resolve(options.gateway) : createCursorGateway(config);
  const slots = new Map<string, Slot>();
  let catalog: { at: number; value: CursorCatalog } | undefined;
  let shuttingDown = false;
  const persist = () => config.config.cursor?.persistSessions !== false;

  async function gateway(): Promise<CursorGateway> {
    try { return await gatewayPromise; }
    catch (error) { throw error instanceof RuntimeError ? error : new RuntimeError("CURSOR_ENGINE_UNAVAILABLE"); }
  }
  async function listed(): Promise<CursorCatalog> {
    if (catalog && Date.now() - catalog.at < 5 * 60_000) return catalog.value;
    const value = await (await gateway()).models();
    catalog = { at: Date.now(), value };
    return value;
  }
  function slotFor(scope: Scope, sessionId: string): Slot {
    if (shuttingDown) throw new RuntimeError("RUNTIME_SHUTTING_DOWN");
    const key = scopeKey(scope);
    const existing = slots.get(key);
    if (existing) {
      if (existing.sessionId !== sessionId || existing.closing) throw new RuntimeError("RUNTIME_SCOPE_BUSY");
      return existing;
    }
    const slot: Slot = { scope, sessionId, preface: "", introduced: false, closing: false, switching: false };
    slots.set(key, slot);
    return slot;
  }
  function live(slot: Slot, turn: Turn): boolean {
    return !shuttingDown && !slot.closing && slot.turn === turn && !turn.terminal && !turn.cancelling &&
      !turn.controller.signal.aborted && !slot.options?.signal?.aborted;
  }
  function emit(slot: Slot, event: RuntimeEvent): void {
    try { slot.options?.onEvent(event); } catch { diagnostics.record("RUNTIME_EVENT_HANDLER_FAILED"); }
  }
  function settle(slot: Slot, turn: Turn, event: RuntimeEvent): void {
    if (turn.terminal) return;
    turn.terminal = true;
    emit(slot, event);
  }
  async function close(slot: Slot): Promise<void> {
    slot.closed ??= closeOwned(slot);
    return slot.closed;
  }
  async function closeOwned(slot: Slot): Promise<void> {
    slot.closing = true;
    slot.turn?.controller.abort();
    try { await slot.agent?.close(); }
    catch { diagnostics.record("RUNTIME_LOSS_CLEANUP_FAILED"); }
    finally { if (slots.get(scopeKey(slot.scope)) === slot) slots.delete(scopeKey(slot.scope)); }
  }
  async function sessionSpec(slot: Slot, session: Session): Promise<{ spec: Omit<CursorSessionSpec, "resumeId" | "model">; preface: string }> {
    const user = session.scope.ownerId;
    const owner = user === config.config.ownerId;
    const match = authorizedWorkspace(config.config, user, session.scope.botId, session.workspace);
    if (!match) throw new RuntimeError("WORKSPACE_ACCESS_DENIED");
    const agents = match === DEFAULT_WORKSPACE_ID ? config.agents : config.agents.filter((agent) => match.agentIds.includes(agent.id));
    const main = agents.find((agent) => agent.id === session.agentId);
    if (!main) throw new RuntimeError("RUNTIME_AGENT_MISSING");
    const linked = linkedWorkspaces(config.config, session.workspace);
    const prompt = async (agent: AgentDefinition) =>
      `Source: ${relative(session.workspace, agent.canonicalPath)}\n${await readFile(agent.canonicalPath, "utf8")}`;
    const subagents: CursorSessionSpec["agents"] = {};
    for (const agent of agents.filter((entry) => entry.id !== session.agentId)) {
      subagents[agent.id] = { description: agent.description, prompt: await prompt(agent) };
    }
    const instructions = await workspaceInstructions(session.workspace);
    const sessionModules = options.modules
      ? await buildSessionModules(options.modules, { agentId: session.agentId, owner })
      : { instructions: "", abilities: [] };
    const moduleGuard: ModuleToolGuard | undefined = options.modules && {
      host: options.modules, diagnostics,
      call: () => {
        const turn = slot.turn;
        if (!turn || !live(slot, turn)) return undefined;
        return { scope: slot.scope, agentId: session.agentId, userId: user, owner, workspace: session.workspace,
          signal: turn.controller.signal };
      },
    };
    const telegram = owner
      ? `You are chatting with ${ownerLabel(config.config)} in Telegram. Do not use structured question forms. ` +
        "If you need clarification, ask in plain text, one question at a time, then end your turn and wait for their reply."
      : `You are chatting with ${userLabel(config.config.users?.find((entry) => entry.telegramUserId === user)?.displayName)} in Telegram. ` +
        "Do not use structured question forms. " +
        "If you need clarification, ask in plain text, one question at a time, then end your turn and wait for their reply. " +
        "Work only inside the current workspace directory; never read, list or modify anything outside it, including repository metadata.";
    const tools: Record<string, CursorTool> = {
      densemble_export_file: {
        description: "Return a generated workspace file to this conversation. A path mentioned in text is not an export.",
        inputSchema: { type: "object", properties: { path: { type: "string", description: "Absolute path or a path relative to the configured workspace." } }, required: ["path"] },
        async execute(args) {
          const turn = slot.turn;
          const exportFile = slot.options?.exportFile;
          if (typeof args.path !== "string" || !turn || !live(slot, turn) || !exportFile) {
            return { ok: false, code: "EXPORT_NOT_AUTHORIZED" };
          }
          const attachment = await exportFile(turn.identity, args.path, turn.controller.signal);
          if (!live(slot, turn)) return { ok: false, code: "EXPORT_CANCELLED" };
          return { status: "prepared_for_delivery", fileName: attachment.fileName };
        },
      },
      densemble_manage_proactivity: {
        description: "Manage this agent's own proactive reminders and check-ins for the current chat scope. Returns a result object with `ok`, `code`, and `message`; if `ok` is false, relay the `message` to the user.",
        inputSchema: jsonSchema(proactivityRequestSchema),
        async execute(args) {
          const turn = slot.turn;
          const parsed = proactivityRequestSchema.safeParse(args);
          const proactivity = slot.options?.proactivity;
          if (!turn || !live(slot, turn) || !proactivity || !parsed.success) {
            return { ok: false, code: "INVALID_REQUEST", message: "Проактивність недоступна для цього виконання." };
          }
          return proactivity(slot.scope, session.agentId, parsed.data as ProactivityRequest);
        },
      },
    };
    if (moduleGuard) {
      for (const ability of sessionModules.abilities) {
        tools[ability.spec.name] = {
          description: ability.spec.description,
          inputSchema: abilityParameters(ability),
          execute: (args) => invokeGuarded(ability, args, moduleGuard),
        };
      }
    }
    const preface = [
      `# Persona: ${main.id}\nYou are this agent for the whole conversation.\n${await prompt(main)}`,
      ...instructions.map((entry) => `# Workspace instructions\nSource: ${entry.source}\n${entry.text}`),
      `# Densemble service\n${telegram}${linkedWorkspacesInstruction(linked)}\n` +
        "Use `densemble_export_file` to return a generated workspace file to this chat. A path mentioned in text is not an export. " +
        "Use `densemble_manage_proactivity` for your own reminders and check-ins in this chat." +
        (sessionModules.abilities.length ? ` Module abilities: ${sessionModules.abilities.map((ability) => `\`${ability.spec.name}\``).join(", ")}.` : ""),
      ...(sessionModules.instructions ? [sessionModules.instructions] : []),
    ].join("\n\n");
    return { preface, spec: { cwd: session.workspace, dirs: linked.map((entry) => entry.path), sandbox: !owner, agents: subagents, tools } };
  }
  function noteText(slot: Slot, turn: Turn, text: string): void {
    if (!live(slot, turn)) return;
    turn.preview += text;
    if (Date.now() - turn.lastPreview >= (options.previewIntervalMs ?? 750)) {
      turn.lastPreview = Date.now();
      emit(slot, { ...turn.identity, kind: "delta", text: turn.preview });
    }
  }
  async function finish(slot: Slot, turn: Turn, run: CursorRunHandle): Promise<void> {
    try {
      const result = await run.wait();
      if (turn.terminal || !live(slot, turn)) return;
      if (result.status === "cancelled") {
        settle(slot, turn, { ...turn.identity, kind: "stopped", forced: false, externalOutcomeUnknown: true });
        return;
      }
      const text = result.result ?? "";
      if (result.status !== "finished" || !text.trim()) {
        settle(slot, turn, { ...turn.identity, kind: "failed", code: result.status === "error" ? failureFrom(result) : "RUNTIME_TURN_FAILED" });
        return;
      }
      settle(slot, turn, { ...turn.identity, kind: "completed", text });
    } catch {
      if (!turn.terminal) settle(slot, turn, { ...turn.identity, kind: "failed", code: "CURSOR_SERVICE_ERROR" });
    }
  }

  return {
    recoverOwnedProcesses: async () => undefined,
    supportsSteering: () => true,
    async open(supplied) {
      supplied.signal?.throwIfAborted();
      const session = supplied.session;
      if (session.engine !== "cursor") throw new RuntimeError("SESSION_ENGINE_MISMATCH");
      // The Cursor SDK has no per-server tool allowlist, so an allowlisted MCP server would expose every tool.
      if (config.config.mcp.mode === "allowlist") throw new RuntimeError("MCP_TOOL_ALLOWLIST_REQUIRED");
      const slot = slotFor(session.scope, session.id);
      slot.options = supplied;
      if (slot.agent) return { providerSessionId: slot.agent.agentId };
      slot.opening ??= (async () => {
        try {
          const provider = session.providerSessionId;
          if (provider && !cursorAgentId.test(provider)) throw new RuntimeError("UNOWNED_PROVIDER_SESSION");
          const empty = supplied.emptyHistory ?? session.generation === 0;
          const resumeId = persist() && provider && !empty ? provider : undefined;
          const available = await listed();
          if (!available.accepted.has(session.appliedModel)) throw new RuntimeError("MODEL_UNAVAILABLE");
          const built = await sessionSpec(slot, session);
          if (built.spec.sandbox) await assertCursorGuestSandbox(options.sandboxPolicyPath);
          supplied.signal?.throwIfAborted();
          if (slot.closing) throw new RuntimeError("SESSION_OPEN_CANCELLED");
          const client = await gateway();
          if (!resumeId && provider) {
            try { await client.remove(provider); }
            catch { diagnostics.record("CURSOR_SESSION_CLEANUP_FAILED"); }
          }
          const agent = await client.open({ ...built.spec, model: session.appliedModel, ...(resumeId ? { resumeId } : {}) });
          if (slot.closing || supplied.signal?.aborted) throw new RuntimeError("SESSION_OPEN_CANCELLED");
          slot.agent = agent;
          slot.preface = built.preface;
          slot.introduced = Boolean(resumeId);
          slot.model = session.appliedModel;
          return { providerSessionId: agent.agentId };
        } catch (error) {
          await close(slot);
          throw error;
        }
      })();
      return slot.opening;
    },
    async execute(command: RuntimeCommand) {
      const slot = slots.get(scopeKey(command.identity.scope));
      if (!slot || slot.sessionId !== command.identity.sessionId) {
        if (command.kind === "stop") return;
        throw new RuntimeError("RUNTIME_SESSION_NOT_OPEN");
      }
      if (command.kind === "stop") {
        const turn = slot.turn;
        if (turn && (turn.identity.runId !== command.identity.runId || turn.identity.generation !== command.identity.generation)) return;
        if (turn && !turn.terminal) {
          turn.cancelling = true;
          turn.controller.abort();
          let forced = false;
          try { if (turn.run) await bounded(turn.run.cancel(), options.abortGraceMs ?? 2_000, "ABORT_ACK_TIMEOUT"); }
          catch { forced = true; diagnostics.record("RUNTIME_ABORT_FORCED"); }
          settle(slot, turn, { ...turn.identity, kind: "stopped", forced, externalOutcomeUnknown: true });
        }
        if (!slot.options || !turn || slot.options.session.generation === command.identity.generation) await close(slot);
        return;
      }
      if (command.kind === "answer") return;
      if (command.kind === "steer") {
        const turn = slot.turn;
        if (!turn || turn.terminal || turn.identity.runId !== command.identity.runId || !turn.run?.steer) {
          throw new RuntimeError("STEERING_UNSUPPORTED");
        }
        const text = command.input.images.length
          ? `${command.input.text}\n\nAttached files you can read: ${command.input.images.map((image) => image.path).join(", ")}`
          : command.input.text;
        const outcome = await turn.run.steer(text);
        if (outcome !== "complete_delivered") throw new RuntimeError("STEERING_UNSUPPORTED");
        return;
      }
      if (!slot.agent || slot.switching || slot.closing) throw new RuntimeError("RUNTIME_SESSION_NOT_READY");
      if (slot.turn && !slot.turn.terminal) throw new RuntimeError("RUNTIME_TURN_ACTIVE");
      const turn: Turn = { identity: command.identity, controller: new AbortController(), preview: "", lastPreview: 0,
        terminal: false, cancelling: false };
      slot.turn = turn;
      const images = await Promise.all(command.input.images.map(async (image) => {
        if (!imageTypes.has(image.mimeType)) throw new RuntimeError("MODEL_IMAGES_UNSUPPORTED");
        return { mimeType: image.mimeType, data: (await readFile(image.path)).toString("base64") };
      }));
      if (!live(slot, turn)) return;
      const model = slot.model;
      if (!model) throw new RuntimeError("RUNTIME_SESSION_NOT_READY");
      const text = slot.introduced ? command.input.text : `${slot.preface}\n\n# User message\n${command.input.text}`;
      const run = await slot.agent.send({ text, images }, { model, onText: (chunk) => noteText(slot, turn, chunk) });
      slot.introduced = true;
      turn.run = run;
      void finish(slot, turn, run);
    },
    async models(scope, sessionId) {
      const slot = slots.get(scopeKey(scope));
      if (slot?.sessionId === sessionId && slot.agent && !slot.closing) return (await listed()).models;
      return (await listed()).models;
    },
    async setModel(scope, sessionId, model) {
      const slot = slots.get(scopeKey(scope));
      if (!slot?.agent || slot.sessionId !== sessionId || (slot.turn && !slot.turn.terminal) || slot.switching || slot.closing) {
        throw new RuntimeError("MODEL_BOUNDARY_REQUIRED");
      }
      if (!(await listed()).accepted.has(model)) throw new RuntimeError("MODEL_UNAVAILABLE");
      slot.model = model;
    },
    async disconnect(scope, sessionId) {
      const slot = slots.get(scopeKey(scope));
      if (slot?.sessionId !== sessionId) return;
      if (slot.turn && !slot.turn.terminal) throw new RuntimeError("RUNTIME_TURN_ACTIVE");
      await close(slot);
    },
    async deleteSession(scope, sessionId, providerSessionId) {
      if (!cursorAgentId.test(providerSessionId)) throw new RuntimeError("UNOWNED_PROVIDER_SESSION");
      const slot = slots.get(scopeKey(scope));
      if (slot?.sessionId === sessionId) {
        if (slot.turn && !slot.turn.terminal) throw new RuntimeError("RUNTIME_TURN_ACTIVE");
        await close(slot);
      }
      try { await bounded((await gateway()).remove(providerSessionId), 10_000, "SESSION_DELETE_TIMEOUT"); }
      catch (error) { throw error instanceof RuntimeError ? error : new RuntimeError("SESSION_DELETE_FAILED"); }
    },
    async shutdown() {
      shuttingDown = true;
      const results = await Promise.allSettled([...slots.values()].map((slot) => close(slot)));
      if (results.some((entry) => entry.status === "rejected")) throw new RuntimeError("RUNTIME_SHUTDOWN_UNCONFIRMED");
    },
  };
}
