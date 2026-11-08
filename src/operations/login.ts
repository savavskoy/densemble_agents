import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { cursorHome } from "../agents/cursor.js";
import { claudeHome, pinnedClaudePath, serviceUser } from "../agents/claude-env.js";
import { pinnedRuntimePath } from "../agents/copilot.js";
import { enginePlatform } from "../agents/platform.js";
import type { LoadedConfig } from "../config/index.js";
import { checkedPath } from "../config/paths.js";
import { enginePath } from "../platform/engines.js";
import type { Platform } from "../platform/index.js";

export type LoginEngine = "copilot" | "claude";
export interface LoginCommand { executable: string; args: string[]; env: Record<string, string>; home: string }

/**
 * The pinned engine's own login, against the service-owned home only, with a clean environment: no ambient
 * tokens, and the owner's interactive Copilot/Claude logins are never read or changed. Linux (and so the
 * container) uses the device-code flow, completed in a browser on any device.
 */
export async function loginCommand(config: LoadedConfig, engine: LoginEngine, platform: Platform = enginePlatform(),
  user = serviceUser()): Promise<LoginCommand> {
  const home = process.env.HOME;
  if (!home) throw new Error("AUTH_HOME_REQUIRED");
  const base = { HOME: home, PATH: enginePath(platform), LANG: "en_US.UTF-8" };
  if (engine === "copilot") {
    const serviceHome = config.config.runtimeHomePath;
    return { executable: await pinnedRuntimePath(), home: serviceHome,
      args: ["login", ...(platform.os === "linux" ? ["--device-code"] : [])],
      env: { ...base, COPILOT_HOME: serviceHome, COPILOT_AUTO_UPDATE: "false", GH_PROMPT_DISABLED: "1",
        XDG_CONFIG_HOME: join(serviceHome, "xdg"), XDG_CACHE_HOME: join(serviceHome, "cache") } };
  }
  const serviceHome = claudeHome(config);
  return { executable: await pinnedClaudePath(), home: serviceHome, args: ["auth", "login"],
    env: { ...base, USER: user, LOGNAME: user, CLAUDE_CONFIG_DIR: serviceHome, DISABLE_AUTOUPDATER: "1", DISABLE_TELEMETRY: "1" } };
}

/**
 * Browser login for the service-owned Cursor home only. The minted key is stored under `cursor.homePath`
 * and never written into config or the interactive `~/.cursor` directory.
 */
export async function runCursorLogin(config: LoadedConfig): Promise<number> {
  const home = cursorHome(config);
  await mkdir(home, { recursive: true, mode: 0o700 });
  checkedPath(home, "directory");
  try {
    const { Cursor, FileCredentialStore } = await import("@cursor/sdk");
    await Cursor.auth.login({
      store: new FileCredentialStore(join(home, "auth.json")),
      apiKeyName: "densemble",
    });
    return 0;
  } catch {
    process.stderr.write("Cursor login failed. Finish it in the browser, then run make cursor-login again.\n");
    return 1;
  }
}

/** Runs the login interactively in this terminal; resolves with the engine's exit code. */
export async function runLogin(command: LoginCommand): Promise<number> {
  await mkdir(command.home, { recursive: true, mode: 0o700 });
  checkedPath(command.home, "directory");
  return new Promise((resolve, reject) => {
    const child = spawn(command.executable, command.args, { env: command.env, stdio: "inherit", shell: false });
    child.once("error", () => reject(new Error("LOGIN_ENGINE_UNAVAILABLE")));
    child.once("exit", (code, signal) => resolve(code ?? (signal ? 1 : 0)));
  });
}
