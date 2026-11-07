import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { claudePackage, copilotPackage, enginePath } from "../../src/platform/engines.js";
import { supportedPlatform, type PlatformFacts } from "../../src/platform/index.js";
import { executablePath, linuxSnapshot, parseBootId, parseProcStat } from "../../src/platform/processes.js";
import { createModuleHost } from "../../src/modules/host.js";
import { entry, fakeCore, fakeLoader, fakeModule } from "../fixtures/modules/index.js";

const facts = (overrides: Partial<PlatformFacts>): PlatformFacts =>
  ({ platform: "linux", arch: "x64", glibc: true, container: false, ...overrides });

describe("platform detection", () => {
  it("supports Apple Silicon macOS and glibc Linux on x64/arm64", () => {
    expect(supportedPlatform(facts({ platform: "darwin", arch: "arm64", glibc: false }))).toEqual({ id: "darwin-arm64", os: "darwin", container: false });
    expect(supportedPlatform(facts({}))).toEqual({ id: "linux-x64", os: "linux", container: false });
    expect(supportedPlatform(facts({ arch: "arm64", container: true }))).toEqual({ id: "linux-arm64", os: "linux", container: true });
  });

  it("refuses native Windows, musl Linux, Intel macOS and other CPUs", () => {
    for (const unsupported of [
      facts({ platform: "win32" }), facts({ platform: "win32", arch: "arm64" }), facts({ glibc: false }),
      facts({ platform: "darwin", arch: "x64" }), facts({ arch: "ppc64" }), facts({ platform: "freebsd" }),
    ]) expect(supportedPlatform(unsupported)).toBeUndefined();
  });

  it("names the pinned engine packages and PATH per platform", () => {
    const mac = supportedPlatform(facts({ platform: "darwin", arch: "arm64" }))!;
    const linux = supportedPlatform(facts({ arch: "arm64" }))!;
    expect(copilotPackage(mac)).toBe("@github/copilot-darwin-arm64");
    expect(claudePackage(linux)).toBe("@anthropic-ai/claude-agent-sdk-linux-arm64");
    expect(enginePath(mac, "/n/bin/node")).toBe("/n/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin");
    expect(enginePath(linux, "/n/bin/node")).toBe("/n/bin:/usr/local/bin:/usr/bin:/bin");
  });

  it("has every engine package of each supported platform in the lockfile", () => {
    const lock = readFileSync("package-lock.json", "utf8");
    for (const id of ["darwin-arm64", "linux-x64", "linux-arm64"] as const) {
      const platform = { id, os: id.startsWith("darwin") ? "darwin" : "linux", container: false } as const;
      expect(lock).toContain(`"node_modules/${copilotPackage(platform)}"`);
      expect(lock).toContain(`"node_modules/${claudePackage(platform)}"`);
    }
  });
});

describe("Linux process table", () => {
  const stat = (pid: number, comm: string, state: string, ppid: number, start: number) =>
    `${pid} (${comm}) ${state} ${ppid} ${Array.from({ length: 17 }, () => "0").join(" ")} ${start} 1000 20\n`;

  it("parses comm with spaces and parentheses, start ticks and the executable", () => {
    expect(parseProcStat(stat(42, "a (b) c)", "S", 7, 12345), "0b5e7d1c-2f4a-4c39-9a7e-3d1f6b8e2a10", "/app/copilot")).toEqual(
      { pid: 42, parent: 7, started: "0b5e7d1c-2f4a-4c39-9a7e-3d1f6b8e2a10+12345", command: "/app/copilot", state: "S" });
    expect(parseProcStat(stat(43, "kworker/0:1", "T", 2, 9), "1"))
      .toMatchObject({ command: "[kworker/0:1]", state: "T" });
  });

  it("names the program, not the emulator, under Rosetta or QEMU", () => {
    const cmdline = () => "/app/node_modules/@github/copilot-linux-x64/copilot\0--no-auto-update\0";
    expect(executablePath("/usr/local/bin/node", cmdline)).toBe("/usr/local/bin/node");
    expect(executablePath("/run/rosetta/rosetta", cmdline)).toBe("/app/node_modules/@github/copilot-linux-x64/copilot");
    expect(executablePath("/usr/bin/qemu-x86_64", cmdline)).toBe("/app/node_modules/@github/copilot-linux-x64/copilot");
    expect(executablePath("/run/rosetta/rosetta", () => "node\0-e\0")).toBeUndefined();
    // Rosetta's actual layout, as seen in an amd64 container on Apple Silicon.
    expect(executablePath("/run/rosetta/rosetta",
      () => "/run/rosetta/rosetta\0/usr/local/bin/node\0/usr/local/bin/node\0--no-opt\0-e\0x\0")).toBe("/usr/local/bin/node");
    expect(executablePath("/usr/bin/gone (deleted)", cmdline)).toBeUndefined();
    expect(executablePath(undefined, cmdline)).toBeUndefined();
  });

  it("drops zombies and rejects malformed lines", () => {
    expect(parseProcStat(stat(5, "dead", "Z", 1, 3), "1")).toBeUndefined();
    expect(() => parseProcStat("garbage", "1")).toThrow("PROCESS_LIST_INVALID");
    expect(() => parseProcStat("5 (x) S 1", "1")).toThrow("PROCESS_LIST_INVALID");
    expect(() => parseBootId("not-a-boot-id")).toThrow("PROCESS_LIST_INVALID");
  });

  describe("snapshot", () => {
    let root: string;
    beforeEach(() => { root = mkdtempSync(join(tmpdir(), "densemble-proc-")); });
    afterEach(() => { rmSync(root, { recursive: true, force: true }); });

    it("reads every numeric entry, prefers exe, and skips processes that vanished", () => {
      // The boot id, not /proc/stat btime: btime moves when the clock is stepped.
      mkdirSync(join(root, "sys/kernel/random"), { recursive: true });
      writeFileSync(join(root, "sys/kernel/random/boot_id"), "0b5e7d1c-2f4a-4c39-9a7e-3d1f6b8e2a10\n");
      for (const [pid, comm, ppid] of [[1, "tini", 0], [20, "node", 1]] as const) {
        mkdirSync(join(root, String(pid)));
        writeFileSync(join(root, String(pid), "stat"), stat(pid, comm, "S", ppid, pid * 10));
      }
      symlinkSync("/usr/local/bin/node", join(root, "20", "exe"));
      mkdirSync(join(root, "21")); // exited between listing and reading
      mkdirSync(join(root, "self"));
      mkdirSync(join(root, "sys", "1"), { recursive: true }); // non-numeric top-level entries are ignored
      expect(linuxSnapshot(root).sort((a, b) => a.pid - b.pid)).toEqual([
        { pid: 1, parent: 0, started: "0b5e7d1c-2f4a-4c39-9a7e-3d1f6b8e2a10+10", command: "[tini]", state: "S" },
        { pid: 20, parent: 1, started: "0b5e7d1c-2f4a-4c39-9a7e-3d1f6b8e2a10+200", command: "/usr/local/bin/node", state: "S" },
      ]);
    });
  });
});

describe("module platforms", () => {
  it("reports a module that does not support this OS as unavailable without starting it", async () => {
    let started = false;
    const mac = fakeModule("maconly", { platforms: ["darwin"], start: async () => { started = true; return { stop: async () => undefined }; } });
    const any = fakeModule("anywhere");
    const runtime = mkdtempSync(join(tmpdir(), "densemble-modules-"));
    try {
      const host = createModuleHost({ entries: [entry("maconly"), entry("anywhere")], loader: fakeLoader([mac, any]),
        core: fakeCore(), runtimeDataPath: runtime, diagnostics: { record: () => undefined },
        readInstructions: async () => "# instructions", os: "linux" });
      await host.start();
      expect(started).toBe(false);
      expect(host.report().find((row) => row.id === "maconly")).toMatchObject({ state: "unavailable",
        code: "MODULE_PLATFORM_UNSUPPORTED", cause: expect.stringContaining("платформі"), fix: expect.stringContaining("modules.maconly") });
      expect(host.health("anywhere")?.state).toBe("ready");
      await host.stop();
    } finally { rmSync(runtime, { recursive: true, force: true }); }
  });

  it("keeps recordings and reels to macOS in this stage", async () => {
    const recordings = (await import("../../src/modules/recordings/index.js")).module;
    const reels = (await import("../../src/modules/reels/index.js")).module;
    expect(recordings.platforms).toEqual(["darwin"]);
    expect(reels.platforms).toEqual(["darwin"]);
  });
});

describe("platform boundary", () => {
  it("lets only src/platform/ read process.platform or process.arch", () => {
    const offenders: string[] = [];
    const walk = (directory: string): void => {
      for (const name of readdirSync(directory)) {
        const path = join(directory, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (name.endsWith(".ts") && /process\.(platform|arch)\b/.test(readFileSync(path, "utf8"))) offenders.push(relative("src", path));
      }
    };
    walk("src");
    expect(offenders.filter((path) => !path.startsWith("platform/"))).toEqual([]);
  });
});
