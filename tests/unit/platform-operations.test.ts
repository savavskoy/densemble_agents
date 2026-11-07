import { describe, expect, it } from "vitest";
import { parseArguments } from "../../src/operations/arguments.js";
import { assertNotRoot, assertStateMounted, ephemeralPaths, parseMountInfo } from "../../src/platform/environment.js";
import type { Platform } from "../../src/platform/index.js";
import { serviceUnit, systemdTemplate } from "../../src/platform/service-unit.js";
import { launchdTemplate } from "../../src/operations/launchd.js";

const linux: Platform = { id: "linux-arm64", os: "linux", container: true };
const mountInfo = [
  "1 0 0:1 / / rw,relatime - overlay overlay rw",
  "2 1 0:2 / /state rw,relatime - fakeowner /dev/vda1 rw",
  "3 1 0:3 / /tmp rw,nosuid - tmpfs tmpfs rw",
  "4 1 0:4 / /workspaces/my\\040notes rw - virtiofs share rw",
].join("\n");

describe("start guards", () => {
  it("refuses root and accepts any other user", () => {
    expect(() => assertNotRoot(0)).toThrow("CONTAINER_ROOT_FORBIDDEN");
    expect(() => assertNotRoot(10001)).not.toThrow();
    expect(() => assertNotRoot(undefined)).not.toThrow();
  });

  it("parses mount points with escapes and types", () => {
    expect(parseMountInfo(mountInfo)).toEqual([
      { path: "/", type: "overlay" }, { path: "/state", type: "fakeowner" },
      { path: "/tmp", type: "tmpfs" }, { path: "/workspaces/my notes", type: "virtiofs" },
    ]);
  });

  it("finds state that would vanish with the container: on its root, on tmpfs, or a sibling prefix", () => {
    const mounts = parseMountInfo(mountInfo);
    expect(ephemeralPaths(["/state/data", "/state", "/tmp/data", "/srv/data", "/statefile/x"], mounts))
      .toEqual(["/tmp/data", "/srv/data", "/statefile/x"]);
  });

  it("uses the mount stacked last on one mount point, the visible one", () => {
    const bind = { path: "/state", type: "ext4" };
    const tmpfs = { path: "/state", type: "tmpfs" };
    expect(ephemeralPaths(["/state/data"], [{ path: "/", type: "overlay" }, bind, tmpfs])).toEqual(["/state/data"]);
    expect(ephemeralPaths(["/state/data"], [{ path: "/", type: "overlay" }, tmpfs, bind])).toEqual([]);
  });

  it("checks mounts only in a container", () => {
    expect(() => assertStateMounted(linux, ["/state/data", "/state/copilot"], () => mountInfo)).not.toThrow();
    expect(() => assertStateMounted(linux, ["/state/data", "/data"], () => mountInfo)).toThrow("CONTAINER_STATE_NOT_MOUNTED");
    expect(() => assertStateMounted({ ...linux, container: false }, ["/data"], () => { throw new Error("not read"); })).not.toThrow();
  });
});

describe("login and service-unit arguments", () => {
  it("parses login with an engine and the config flag", () => {
    expect(parseArguments(["login", "copilot", "--config", "/c.json"])).toEqual({ command: "login", engine: "copilot", config: "/c.json" });
    expect(parseArguments(["login", "claude"], {})).toEqual({ command: "login", engine: "claude", config: "config.local.json" });
    expect(() => parseArguments(["login"])).toThrow("LOGIN_ENGINE_REQUIRED");
    expect(() => parseArguments(["login", "--config", "/c.json"])).toThrow("LOGIN_ENGINE_REQUIRED");
    expect(() => parseArguments(["login", "codex"])).toThrow("LOGIN_ENGINE_REQUIRED");
    expect(parseArguments(["service-unit", "--config", "/c.json"])).toEqual({ command: "service-unit", config: "/c.json" });
  });

  it("takes the config path from DENSEMBLE_CONFIG (the container) unless --config is given", () => {
    const env = { DENSEMBLE_CONFIG: "/config/config.json" };
    expect(parseArguments(["login", "copilot"], env)).toEqual({ command: "login", engine: "copilot", config: "/config/config.json" });
    expect(parseArguments([], env)).toEqual({ command: "start", config: "/config/config.json" });
    expect(parseArguments(["doctor", "--config", "/other.json"], env)).toEqual({ command: "doctor", config: "/other.json" });
    expect(parseArguments(["doctor"], {})).toEqual({ command: "doctor", config: "config.local.json" });
  });
});

describe("service unit", () => {
  const options = { node: "/usr/bin/node", codeRoot: "/opt/densemble", config: "/etc/dense mble/config 100%$HOME.json", logs: "/var/lib/densemble/logs" };

  it("is the unchanged launchd plist on macOS", () => {
    const mac: Platform = { id: "darwin-arm64", os: "darwin", container: false };
    expect(serviceUnit(mac, options)).toBe(launchdTemplate(options));
  });

  it("is a hardened systemd user unit on Linux with quoted, escaped arguments", () => {
    const unit = serviceUnit({ ...linux, container: false }, options);
    expect(unit).toContain('ExecStart="/usr/bin/node" "/opt/densemble/dist/main.js" "start" "--config" "/etc/dense mble/config 100%%$$HOME.json"');
    expect(unit).toContain("WorkingDirectory=/opt/densemble\n");
    expect(unit).toContain("Restart=always");
    expect(unit).toContain("UMask=0077");
    expect(unit).toContain("NoNewPrivileges=yes");
    expect(unit).toContain("StandardError=append:/var/lib/densemble/logs/service-error.log");
    expect(unit).toContain("WantedBy=default.target");
  });

  it("rejects relative paths and paths systemd cannot quote", () => {
    expect(() => systemdTemplate({ ...options, node: "node" })).toThrow("SERVICE_UNIT_ABSOLUTE_PATHS_REQUIRED");
    expect(() => systemdTemplate({ ...options, logs: "/var/my logs" })).toThrow("SERVICE_UNIT_PATH_WITH_SPACES_UNSUPPORTED");
    expect(() => systemdTemplate({ ...options, config: "/a\nb" })).toThrow("SERVICE_UNIT_ABSOLUTE_PATHS_REQUIRED");
  });
});

describe("container configuration example", () => {
  it("is a valid strict configuration with container paths only", async () => {
    const { readFileSync } = await import("node:fs");
    const { configSchema } = await import("../../src/config/index.js");
    const example = JSON.parse(readFileSync("docker/config.container.example.json", "utf8")) as Record<string, unknown>;
    expect(configSchema.safeParse(example).success).toBe(true);
    const paths = JSON.stringify(example).match(/"\/[^"]*"/g) ?? [];
    expect(paths.every((path) => /^"\/(workspaces|config|state|models|usr)\//.test(path))).toBe(true);
  });
});
