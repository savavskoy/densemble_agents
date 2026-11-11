import { mkdirSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LoadedConfig } from "../../src/config/index.js";

const created: { local?: { settingSources?: unknown; sandboxOptions?: unknown } }[] = [];
vi.mock("@cursor/sdk", () => ({
  FileCredentialStore: class {
    async load() { return { apiKey: "synthetic-key" }; }
  },
  JsonlLocalAgentStore: class {},
  Agent: {
    create: vi.fn(async (options: { local?: { settingSources?: unknown; sandboxOptions?: unknown } }) => {
      created.push(options);
      return { agentId: "agent-synthetic", async [Symbol.asyncDispose]() { return undefined; } };
    }),
  },
}));

const { createCursorGateway } = await import("../../src/agents/cursor.js");

const roots: string[] = [];
afterEach(() => {
  created.splice(0);
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("cursor gateway", () => {
  it("loads no project settings, so a workspace cannot add host hooks or MCP", async () => {
    const root = resolve(".cache", `cursor-gateway-${randomUUID()}`);
    roots.push(root);
    mkdirSync(root, { recursive: true });
    const gateway = await createCursorGateway({ config: { cursor: { homePath: root, defaultModel: "grok-4.7" } } } as LoadedConfig);
    await gateway.open({
      cwd: join(root, "workspace"), dirs: [], model: "grok-4.7", sandbox: false, agents: {}, tools: {},
    });
    expect(created[0]?.local?.settingSources).toEqual([]);
    expect(created[0]?.local?.sandboxOptions).toEqual({ enabled: false });
  });
});
