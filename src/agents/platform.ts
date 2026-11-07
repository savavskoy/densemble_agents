import { currentPlatform, PlatformError, type Platform } from "../platform/index.js";
import { RuntimeError } from "./contracts.js";

/** The running platform for engine code, failing with the same `RuntimeError` type as other engine faults. */
export function enginePlatform(): Platform {
  try { return currentPlatform(); }
  catch (error) { throw error instanceof PlatformError ? new RuntimeError(error.code) : error; }
}
