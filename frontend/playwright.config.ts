import { defineConfig, devices } from "@playwright/test";

/**
 * E2e dziala na ZYWEJ atrapie API Etapu 3 (http://127.0.0.1:8000) - ten
 * serwer NIE jest tu uruchamiany ani gaszony (ma dzialac juz wczesniej,
 * patrz SPEC_ETAP4.md). Playwright startuje tylko frontend (next dev) na
 * porcie 3000; `reuseExistingServer: false`, zeby nigdy nie podpiac sie pod
 * recznie odpalony `npm run dev` z innej sesji.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: false,
    timeout: 60_000,
    // Brak nadpisania API_URL_WEWNETRZNY - proxy (app/api/[...sciezka]/route.ts)
    // uzywa wtedy swojej wartosci domyslnej http://localhost:8000, dokladnie
    // jak przy recznym smoke-testowaniu przez przegladarke (dzialalo poprawnie).
  },
});
