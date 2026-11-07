import { readFileSync } from "node:fs";
import { resolve, sep } from "node:path";
import { PlatformError, type Platform } from "./index.js";

/** Agents get a shell; running them with administrator rights is never allowed, in a container or not. */
export function assertNotRoot(uid: number | undefined = process.getuid?.()): void {
  if (uid === 0) throw new PlatformError("CONTAINER_ROOT_FORBIDDEN");
}

export interface MountPoint { path: string; type: string }

/** Mount points from `/proc/self/mountinfo` (field 5, octal escapes decoded; type after the ` - ` separator). */
export function parseMountInfo(text: string): MountPoint[] {
  return text.split("\n").flatMap((line) => {
    const [left, right] = line.split(" - ");
    const path = left?.split(" ")[4];
    const type = right?.split(" ")[0];
    if (!path || !type) return [];
    return [{ path: path.replace(/\\([0-7]{3})/g, (_match, octal: string) => String.fromCharCode(parseInt(octal, 8))), type }];
  });
}

/**
 * Paths whose deepest enclosing mount is the container's own root or a tmpfs: their contents vanish with
 * the container. Instance state must sit on a mount the owner provided (a bind mount or a named volume).
 */
export function ephemeralPaths(paths: readonly string[], mounts: readonly MountPoint[]): string[] {
  return paths.filter((path) => {
    const absolute = resolve(path);
    // Deepest mount point wins; of mounts stacked on one point, the last listed is the visible one.
    const enclosing = mounts
      .filter((mount) => mount.path === "/" || absolute === mount.path || absolute.startsWith(`${mount.path}${sep}`))
      .reduce<MountPoint | undefined>((best, mount) => !best || mount.path.length >= best.path.length ? mount : best, undefined);
    return !enclosing || enclosing.path === "/" || enclosing.type === "tmpfs";
  });
}

/** In a container, refuses state that would be lost when the container is recreated. */
export function assertStateMounted(platform: Platform, paths: readonly string[],
  mountInfo: () => string = () => readFileSync("/proc/self/mountinfo", "utf8")): void {
  if (!platform.container) return;
  if (ephemeralPaths(paths, parseMountInfo(mountInfo())).length) throw new PlatformError("CONTAINER_STATE_NOT_MOUNTED");
}
