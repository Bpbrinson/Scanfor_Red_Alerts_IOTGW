/**
 * fingerprint.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Utility functions for normalizing alert data into a stable fingerprint.
 *
 * The fingerprint strips the daily date suffix from log filenames so the same
 * recurring issue gets the same key every day.
 *
 * Format:  env | hostPrefix | logScope | errorType
 * Example: prod | mxqrpiog  | listener-main | SQLException
 */

/**
 * Extracts the environment prefix from a hostname.
 * For now everything is "prod" — extend this when staging/dev hosts are added.
 */
function extractEnv(hostname) {
  if (/staging|stg/i.test(hostname)) return "staging";
  if (/dev|test/i.test(hostname)) return "dev";
  return "prod";
}

/**
 * Strips the trailing numeric node index from a hostname and returns the
 * stable prefix used in the fingerprint.
 * e.g. mxqrpiog02  →  mxqrpiog
 *      ccgw-eastus2-prod-ford-vm-01  →  ccgw-eastus2-prod-ford
 */
function extractHostPrefix(hostname) {
  // Remove trailing -vm-NN or trailing numeric suffix
  return hostname
    .replace(/-vm-\d+$/, "")   // ccgw-eastus2-prod-ford-vm-01 → ccgw-eastus2-prod-ford
    .replace(/\d+$/, "");      // mxqrpiog02 → mxqrpiog
}

/**
 * Strips the date suffix from a log filename.
 * e.g. listener-main.20260630  →  listener-main
 */
function extractLogScope(logFile) {
  return logFile.replace(/\.\d{8}$/, "");
}

/**
 * Builds the normalized fingerprint string for an alert object.
 * @param {object} alert - must have { hostname, logFile, errorType }
 * @returns {string} fingerprint
 */
function buildFingerprint(alert) {
  const env = extractEnv(alert.hostname);
  const hostPrefix = extractHostPrefix(alert.hostname);
  const logScope = extractLogScope(alert.logFile);
  return `${env} | ${hostPrefix} | ${logScope} | ${alert.errorType}`;
}
