import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// RTL rejestruje auto-cleanup tylko gdy wykryje globalny `afterEach` (np. gdy
// `test.globals: true`). Nasza konfiguracja go nie wlacza, wiec bez tego
// kazdy kolejny test w tym samym pliku widzialby DOM z poprzednich renderow.
afterEach(() => {
  cleanup();
});
