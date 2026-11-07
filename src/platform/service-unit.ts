import { isAbsolute, join } from "node:path";
import { launchdTemplate, type LaunchdOptions } from "../operations/launchd.js";
import type { Platform } from "./index.js";

export type ServiceUnitOptions = LaunchdOptions;

/** systemd `ExecStart` argument: quoted, with `\`, `"`, specifier `%` and variable `$` escaped. */
function systemdArgument(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, "\\\"").replace(/%/g, "%%").replace(/\$/g, "$$$$")}"`;
}

/** A systemd **user** unit for native Linux; printed for the owner to install, never installed by Densemble. */
export function systemdTemplate(options: ServiceUnitOptions): string {
  if (Object.values(options).some((path) => !isAbsolute(path) || /[\u0000-\u001f]/.test(path))) {
    throw new Error("SERVICE_UNIT_ABSOLUTE_PATHS_REQUIRED");
  }
  // `WorkingDirectory=` and `append:` paths cannot be quoted in systemd.
  if (/\s/.test(options.logs) || /\s/.test(options.codeRoot)) throw new Error("SERVICE_UNIT_PATH_WITH_SPACES_UNSUPPORTED");
  const exec = [options.node, join(options.codeRoot, "dist", "main.js"), "start", "--config", options.config].map(systemdArgument).join(" ");
  const [codeRoot, logs] = [options.codeRoot, options.logs].map((path) => path.replace(/%/g, "%%"));
  return `[Unit]
Description=Densemble
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${codeRoot}
ExecStart=${exec}
Restart=always
RestartSec=15
UMask=0077
NoNewPrivileges=yes
StandardOutput=append:${logs}/service.log
StandardError=append:${logs}/service-error.log

[Install]
WantedBy=default.target
`;
}

/** The background-service definition for this platform: a launchd plist on macOS, a systemd user unit on Linux. */
export function serviceUnit(platform: Platform, options: ServiceUnitOptions): string {
  return platform.os === "darwin" ? launchdTemplate(options) : systemdTemplate(options);
}
