import { afterEach, describe, expect, it, vi } from "vitest";
import type { LoadedConfig } from "../../src/config/index.js";
import type { Platform } from "../../src/platform/index.js";

vi.mock("../../src/agents/copilot.js", () => ({ pinnedRuntimePath: async () => "/pinned/copilot" }));
vi.mock("../../src/agents/claude-env.js", () => ({
  pinnedClaudePath: async () => "/pinned/claude",
  serviceUser: () => "service-user",
  claudeHome: (config: LoadedConfig) => config.config.claudeCode!.homePath,
}));
const { loginCommand } = await import("../../src/operations/login.js");

const config = { config: { runtimeHomePath: "/state/copilot", claudeCode: { homePath: "/state/claude", defaultModel: "m" } } } as unknown as LoadedConfig;
const linux: Platform = { id: "linux-x64", os: "linux", container: true };
const mac: Platform = { id: "darwin-arm64", os: "darwin", container: false };

describe("engine login", () => {
  afterEach(() => { vi.unstubAllEnvs(); });

  it("logs Copilot into the service home only, device code on Linux, with no ambient tokens", async () => {
    vi.stubEnv("HOME", "/state/home");
    vi.stubEnv("GH_TOKEN", "ambient");
    const command = await loginCommand(config, "copilot", linux);
    expect(command).toMatchObject({ executable: "/pinned/copilot", args: ["login", "--device-code"], home: "/state/copilot" });
    expect(command.env).toEqual({ HOME: "/state/home", PATH: expect.stringMatching(/:\/usr\/local\/bin:\/usr\/bin:\/bin$/),
      LANG: "en_US.UTF-8", COPILOT_HOME: "/state/copilot", COPILOT_AUTO_UPDATE: "false", GH_PROMPT_DISABLED: "1",
      XDG_CONFIG_HOME: "/state/copilot/xdg", XDG_CACHE_HOME: "/state/copilot/cache" });
    expect((await loginCommand(config, "copilot", mac)).args).toEqual(["login"]);
  });

  it("logs Claude Code into claudeCode.homePath", async () => {
    vi.stubEnv("HOME", "/state/home");
    const command = await loginCommand(config, "claude", linux, "densemble");
    expect(command).toMatchObject({ executable: "/pinned/claude", args: ["auth", "login"], home: "/state/claude" });
    expect(command.env).toMatchObject({ CLAUDE_CONFIG_DIR: "/state/claude", USER: "densemble", DISABLE_AUTOUPDATER: "1" });
    expect(Object.keys(command.env)).not.toContain("ANTHROPIC_API_KEY");
  });
});
