import { execFile, execFileSync } from "node:child_process";
import { readdirSync, readFileSync, readlinkSync } from "node:fs";
import { promisify } from "node:util";
import { currentPlatform, PlatformError, type Platform } from "./index.js";

const exec = promisify(execFile);

/**
 * A process as the supervisor knows it. `started` is opaque and platform-specific; together with
 * `pid` and `command` (the executable path) it tells a process apart from a later one reusing its pid.
 */
export interface ProcessIdentity { pid: number; parent: number; started: string; command: string; state?: string | undefined }
export interface ProcessAccess {
  snapshot(): Promise<ProcessIdentity[]>;
  signal(pid: number, signal: NodeJS.Signals): void;
}

/** macOS: `ps -axo pid=,ppid=,lstart=,stat=,comm=` with `LC_ALL=C`; zombies are dropped. */
export function parseBsdProcesses(text: string): ProcessIdentity[] {
  return text.split("\n").flatMap((line) => {
    if (!line.trim()) return [];
    const match = /^\s*(\d+)\s+(\d+)\s+(\w+\s+\w+\s+\d+\s+[\d:]+\s+\d+)\s+(\S+)\s+(.+)$/.exec(line);
    if (!match) throw new PlatformError("PROCESS_LIST_INVALID");
    return match[4]!.startsWith("Z") ? [] : [{
      pid: Number(match[1]), parent: Number(match[2]), started: match[3]!, command: match[5]!, state: match[4]!,
    }];
  });
}

/**
 * This boot's id; start ticks are relative to the boot. Not `btime` from `/proc/stat`: that is wall-clock
 * time minus uptime and shifts whenever the clock is stepped (NTP, a VM resuming after host sleep).
 */
export function parseBootId(text: string): string {
  const id = text.trim();
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new PlatformError("PROCESS_LIST_INVALID");
  return id;
}

/**
 * Linux: one `/proc/<pid>/stat` line. `comm` sits between the first `(` and the last `)` and may itself
 * contain spaces and parentheses; `executable` (from `/proc/<pid>/exe`) is preferred as the command.
 */
export function parseProcStat(text: string, bootId: string, executable?: string): ProcessIdentity | undefined {
  const open = text.indexOf("(");
  const close = text.lastIndexOf(")");
  if (open < 1 || close < open) throw new PlatformError("PROCESS_LIST_INVALID");
  const pid = Number(text.slice(0, open).trim());
  const fields = text.slice(close + 1).trim().split(/\s+/);
  // After comm: state(3) ppid(4) … starttime(22), numbered as in proc(5).
  const state = fields[0];
  const parent = Number(fields[1]);
  const ticks = fields[19];
  if (!Number.isInteger(pid) || !state || !Number.isInteger(parent) || !ticks || !/^\d+$/.test(ticks)) {
    throw new PlatformError("PROCESS_LIST_INVALID");
  }
  if (state.startsWith("Z") || state.startsWith("X")) return undefined;
  return {
    pid, parent, started: `${bootId}+${ticks}`, command: executable ?? `[${text.slice(open + 1, close)}]`, state,
  };
}

function readOptional(read: () => string): string | undefined {
  try { return read(); } catch { return undefined; }
}

/**
 * The program a process runs. Under user-mode emulation (an amd64 image on Apple Silicon through Rosetta or
 * QEMU) `exe` names the emulator for every process, so the program path from the command line is used instead.
 */
export function executablePath(exe: string | undefined, cmdline: () => string): string | undefined {
  if (exe === undefined || exe.endsWith(" (deleted)")) return undefined;
  if (!/(^|\/)(rosetta|qemu-[^/]+)$/.test(exe)) return exe;
  // The emulator may lead the command line (Rosetta: `rosetta <program> <argv0> …`); skip it.
  const program = readOptional(cmdline)?.split("\0").find((part) => part !== exe);
  return program?.startsWith("/") ? program : undefined;
}

/** Linux: the process table straight from `/proc`, no `procps` needed (slim images ship without it). */
export function linuxSnapshot(root = "/proc"): ProcessIdentity[] {
  const bootId = parseBootId(readFileSync(`${root}/sys/kernel/random/boot_id`, "utf8"));
  return readdirSync(root).flatMap((name) => {
    if (!/^\d+$/.test(name)) return [];
    // A process may exit between listing and reading; it is simply absent from this snapshot.
    const stat = readOptional(() => readFileSync(`${root}/${name}/stat`, "utf8"));
    if (stat === undefined) return [];
    const identity = parseProcStat(stat, bootId, executablePath(
      readOptional(() => readlinkSync(`${root}/${name}/exe`)), () => readFileSync(`${root}/${name}/cmdline`, "utf8")));
    return identity ? [identity] : [];
  });
}

const PS_ARGS = ["-axo", "pid=,ppid=,lstart=,stat=,comm="];
const PS_OPTIONS = {
  encoding: "utf8", timeout: 2_000, maxBuffer: 2 * 1024 * 1024,
  env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
} as const;

function signal(pid: number, name: NodeJS.Signals): void {
  try { process.kill(pid, name); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw new PlatformError("PROCESS_SIGNAL_FAILED"); }
}

/** Synchronous snapshot for short-lived tools (the SDK gate). */
export function processSnapshotSync(platform: Platform = currentPlatform()): ProcessIdentity[] {
  return platform.os === "linux" ? linuxSnapshot() : parseBsdProcesses(execFileSync("/bin/ps", PS_ARGS, PS_OPTIONS));
}

export const nativeProcesses: ProcessAccess = {
  async snapshot() {
    if (currentPlatform().os === "linux") return linuxSnapshot();
    const { stdout } = await exec("/bin/ps", PS_ARGS, PS_OPTIONS);
    return parseBsdProcesses(stdout);
  },
  signal,
};
