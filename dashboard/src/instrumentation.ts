/**
 * Runs once when the Next.js server starts, before it accepts any request.
 *
 * Checks the settings, so a dashboard with a missing or weak session secret, or
 * no admin API address, stops at once with a clear message instead of failing
 * on the first sign-in.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { checkSettingsOrExit } = await import("./lib/startup-check");
    checkSettingsOrExit();
  }
}
