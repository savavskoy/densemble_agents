import { dirname } from "node:path";
import { currentPlatform, type Platform } from "./index.js";

/** npm package holding the pinned Copilot CLI binary for this platform (an optional dependency). */
export function copilotPackage(platform: Platform = currentPlatform()): string {
  return `@github/copilot-${platform.id}`;
}

/** npm package holding the pinned Claude Code binary bundled with the Agent SDK for this platform. */
export function claudePackage(platform: Platform = currentPlatform()): string {
  return `@anthropic-ai/claude-agent-sdk-${platform.id}`;
}

/** PATH handed to engines: the running Node first, then the platform's usual tool locations. */
export function enginePath(platform: Platform = currentPlatform(), node = process.execPath): string {
  const tools = platform.os === "darwin" ? "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin" : "/usr/local/bin:/usr/bin:/bin";
  return `${dirname(node)}:${tools}`;
}
