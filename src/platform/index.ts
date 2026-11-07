/**
 * The only place that knows which operating system Densemble runs on. Everything platform-specific
 * (engine binaries, process listing, service units, PATH) is answered here; other code never reads
 * `process.platform` or `process.arch` (enforced by tests/unit/platform-boundary.test.ts).
 */
export type PlatformId = "darwin-arm64" | "linux-x64" | "linux-arm64";
export type PlatformOs = "darwin" | "linux";
export interface Platform { id: PlatformId; os: PlatformOs; container: boolean }
export interface PlatformFacts { platform: string; arch: string; glibc: boolean; container: boolean }

export class PlatformError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PlatformError"; }
}

export const UNSUPPORTED_PLATFORM_HINT =
  "Densemble runs natively on Apple Silicon macOS and on Linux (glibc, x64/arm64); elsewhere, including Windows, " +
  "use the Docker image — see docs/platforms.md.\n";

/** Windows has no process groups or job-control signals; everything else Densemble runs on has them. */
export const PROCESS_GROUPS = process.platform !== "win32";
export const PATH_SEPARATOR = process.platform === "win32" ? "\\" : "/";

export function platformFacts(env: NodeJS.ProcessEnv = process.env): PlatformFacts {
  const header = (process.report?.getReport() as { header?: { glibcVersionRuntime?: string } } | undefined)?.header;
  return {
    platform: process.platform, arch: process.arch,
    glibc: typeof header?.glibcVersionRuntime === "string",
    container: env.DENSEMBLE_CONTAINER === "1",
  };
}

/** The supported platform for these facts, or `undefined` (native Windows, musl Linux, Intel macOS, …). */
export function supportedPlatform(facts: PlatformFacts): Platform | undefined {
  const { container } = facts;
  if (facts.platform === "darwin" && facts.arch === "arm64") return { id: "darwin-arm64", os: "darwin", container };
  if (facts.platform === "linux" && facts.glibc && (facts.arch === "x64" || facts.arch === "arm64")) {
    return { id: `linux-${facts.arch}`, os: "linux", container };
  }
  return undefined;
}

let current: Platform | undefined;
/** The running platform; throws `PLATFORM_UNSUPPORTED` anywhere Densemble is not supported natively. */
export function currentPlatform(): Platform {
  current ??= supportedPlatform(platformFacts());
  if (!current) throw new PlatformError("PLATFORM_UNSUPPORTED");
  return current;
}
