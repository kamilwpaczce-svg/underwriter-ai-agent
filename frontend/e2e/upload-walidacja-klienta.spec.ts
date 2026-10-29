import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * Plik .txt jest odrzucany WALIDACJA KLIENTA (lib/walidacja.ts), bez zadnego
 * wywolania sieciowego do API - zero kosztu, zero ryzyka dla zywego serwera.
 * Plik testowy tworzymy w katalogu tymczasowym systemu (NIE w `dane/`, zeby
 * nie dotykac danych testowych Etapu 1-3).
 */
test("plik .txt jest odrzucany po stronie klienta bez wywolania API", async ({ page }) => {
  const zadaniaDoWnioski: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/wnioski") && req.method() === "POST") {
      zadaniaDoWnioski.push(req.url());
    }
  });

  await page.goto("/");

  const sciezkaTxt = path.join(os.tmpdir(), "e2e-niedozwolony-plik.txt");
  fs.writeFileSync(sciezkaTxt, "To nie jest wniosek ubezpieczeniowy.");

  await page.locator('input[type="file"]').setInputFiles(sciezkaTxt);

  await expect(
    page.getByRole("alert").filter({ hasText: /nieobslugiwane/i })
  ).toContainText(/pdf|jpg|jpeg|eml|rozszerzen/i);
  expect(zadaniaDoWnioski).toHaveLength(0);
  // Nie nawigujemy nigdzie - zostajemy na liscie.
  await expect(page).toHaveURL("/");
});
