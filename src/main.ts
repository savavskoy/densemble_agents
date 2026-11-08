import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig, moduleEntries } from "./config/index.js";
import { checkedPath, isWithin } from "./config/paths.js";
import { parseArguments } from "./operations/arguments.js";
import { createDiagnostics } from "./operations/diagnostics.js";
import { assertNotRoot, assertStateMounted } from "./platform/environment.js";
import { currentPlatform, UNSUPPORTED_PLATFORM_HINT } from "./platform/index.js";

const diagnostics = createDiagnostics();
const codeRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

async function main(): Promise<void> {
  const platform = currentPlatform();
  assertNotRoot();
  const args = parseArguments(process.argv.slice(2));
  if (!existsSync(args.config)) {
    process.stderr.write("Densemble is not configured. Create a private config.local.json from config.example.json; credentials stay in your external secrets.local.json.\n");
    process.exitCode = 1;
    return;
  }
  if (process.versions.node.split(".")[0] !== "24") throw new Error("NODE_24_REQUIRED");
  const config = loadConfig(args.config, { codeRoot });
  assertStateMounted(platform, [config.config.runtimeDataPath, config.config.runtimeHomePath,
    ...(config.config.claudeCode ? [config.config.claudeCode.homePath] : [])]);
  if (args.target) {
    const target = resolve(args.target);
    const parent = checkedPath(dirname(target), "directory");
    if (isWithin(codeRoot, parent)) throw new Error("BACKUP_OUTSIDE_CODE_REQUIRED");
  }
  if (args.command === "launchd" || args.command === "service-unit") {
    const { serviceUnit } = await import("./platform/service-unit.js");
    const logs = join(config.config.runtimeDataPath, "logs");
    mkdirSync(logs, { recursive: true, mode: 0o700 });
    checkedPath(logs, "directory");
    process.stdout.write(serviceUnit(platform, {
      node: process.execPath, codeRoot, config: resolve(args.config), logs,
    }));
    return;
  }
  if (args.command === "login") {
    // Holding the instance lock keeps a running service from reading a half-written login.
    const { acquireProcessLock } = await import("./storage/process-lock.js");
    const lock = acquireProcessLock(config.config.runtimeDataPath);
    try {
      if (args.engine === "cursor") {
        const { runCursorLogin } = await import("./operations/login.js");
        process.exitCode = await runCursorLogin(config);
      } else if (args.engine === "copilot" || args.engine === "claude") {
        const { loginCommand, runLogin } = await import("./operations/login.js");
        process.exitCode = await runLogin(await loginCommand(config, args.engine, platform));
      } else {
        throw new Error("LOGIN_ENGINE_REQUIRED");
      }
    } finally { lock.release(); }
    return;
  }
  if (args.command === "recordings-status") {
    // Read-only and lock-free: it only reads the snapshot the running service writes.
    const { formatStatus, readStatus } = await import("./modules/recordings/api.js");
    const configured = moduleEntries(config.config).some((entry) => entry.id === "recordings" && entry.enabled);
    // The module's data directory, then the spec 004 location (renamed at the module's first start).
    const data = config.config.runtimeDataPath;
    const status = configured ? await readStatus(join(data, "modules", "recordings", "status.json")) ??
      await readStatus(join(data, "recordings", "status.json")) : undefined;
    process.stdout.write(args.json
      ? `${JSON.stringify({ configured, status: status ?? null }, null, 2)}\n`
      : formatStatus({ configured, status, now: Date.now() }));
    return;
  }
  if (args.command === "modules-status") {
    // Read-only and lock-free: it only reads the snapshot the running service writes.
    const { formatModulesStatus, isModulesStateStale, modulesStatePath, readModulesState } = await import("./modules/state.js");
    const state = await readModulesState(modulesStatePath(config.config.runtimeDataPath));
    const now = Date.now();
    const agentId = config.config.coordinatorAgentId;
    process.stdout.write(args.json
      ? `${JSON.stringify({ running: Boolean(state && !isModulesStateStale(state, now)), state: state ?? null }, null, 2)}\n`
      : formatModulesStatus({ state, now, ...(agentId ? { agentId } : {}) }));
    return;
  }
  if (args.command === "start") {
    const { startService } = await import("./service.js");
    let stopping = false;
    let service: Awaited<ReturnType<typeof startService>> | undefined;
    const shutdown = () => {
      if (stopping) return;
      stopping = true;
      void service?.stop().catch(() => {
        diagnostics.record("SERVICE_SHUTDOWN_FAILED");
        process.exitCode = 1;
      });
    };
    process.once("SIGINT", shutdown);
    process.once("SIGTERM", shutdown);
    try {
      service = await startService(config);
      if (stopping) await service.stop();
    } catch (error) {
      process.removeListener("SIGINT", shutdown);
      process.removeListener("SIGTERM", shutdown);
      throw error;
    }
    return;
  }
  const { acquireProcessLock } = await import("./storage/process-lock.js");
  const lock = acquireProcessLock(config.config.runtimeDataPath);
  try {
    const { createCopilotRuntime } = await import("./agents/index.js");
    const runtime = createCopilotRuntime({ config, diagnostics });
    try { await runtime.recoverOwnedProcesses(); } finally { await runtime.shutdown(); }
    if (args.command === "doctor") {
      const { doctor } = await import("./operations/doctor.js");
      const report = await doctor(config);
      process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
      process.exitCode = report.ready ? 0 : 2;
    } else if (args.command === "restore") {
      const { restoreService } = await import("./operations/backup.js");
      restoreService(config.config, args.target!);
      diagnostics.record("RESTORE_COMPLETE");
    } else {
      const { openStore } = await import("./storage/index.js");
      const { backupService } = await import("./operations/backup.js");
      const store = openStore({ path: join(config.config.runtimeDataPath, "state.sqlite") });
      try { await backupService(config.config, store, args.target!); } finally { store.close(); }
      diagnostics.record("BACKUP_COMPLETE");
    }
  } finally { lock.release(); }
}

void main().catch((error: unknown) => {
  const code = error instanceof Error && /^[A-Z][A-Z0-9_]{0,95}$/.test(error.message)
    ? error.message : "SERVICE_OPERATION_FAILED";
  if (code === "PLATFORM_UNSUPPORTED") process.stderr.write(UNSUPPORTED_PLATFORM_HINT);
  diagnostics.record(code);
  process.exitCode = 1;
});
