import "server-only";

import { readDashboardConfig } from "./config";

/** Stop the Node.js process with a clear message when a setting is missing or invalid. */
export function checkSettingsOrExit(): void {
  try {
    readDashboardConfig();
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    console.error(`The dashboard cannot start: ${reason}`);
    process.exit(1);
  }
}
