const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Lexical isolation check for tool calls made in a non-owner workspace session. It rejects references to
 * other configured paths, the repository metadata, home-relative paths and parent traversal. It is a
 * defense layer, not a sandbox: the workspace boundary is also enforced by the session working directory.
 */
export function workspaceViolation(payload: unknown, forbiddenRoots: string[]): boolean {
  let text: string;
  try { text = JSON.stringify(payload) ?? ""; } catch { return true; }
  if (text.length > 100_000) return true;
  if (forbiddenRoots.some((root) => new RegExp(`${escape(root)}(?![A-Za-z0-9_-])`).test(text))) return true;
  return /(?:^|[\\/"'\s=:])\.\.(?:[\\/"'\s]|$)|(?:^|[\\/"'\s=:])\.git(?:[\\/"'\s]|$)|~[\\/]|\$\{?HOME\b/.test(text.replaceAll("\\\\", "/").replaceAll("\\n", " "));
}

/** Tells the agent which linked workspaces it may also use, by name and path. Empty when there are none. */
export function linkedWorkspacesInstruction(linked: { name: string; path: string }[]): string {
  if (!linked.length) return "";
  return " Linked workspaces you may also read and change, each with its own `AGENTS.md` rules for its folder: " +
    linked.map((workspace) => `${workspace.name} (\`${workspace.path}\`)`).join(", ") + ".";
}
