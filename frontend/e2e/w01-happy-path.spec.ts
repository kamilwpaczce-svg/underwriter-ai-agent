import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * W01: rekomendacja LLM i decyzja silnika zweryfikowane na zywym API jako
 * obie "AKCEPTACJA" (patrz GET /wnioski/8ec9ccbf-6f44-4c18-a0f7-71ed6735fa6d).
 * Pelna sciezka: upload -> PRZETWARZANIE -> CZEKA_NA_DECYZJE -> decyzja
 * ZGODNA z rekomendacja i silnikiem (komentarz opcjonalny, pomijamy go) ->
 * ZAKONCZONY -> audyt ma nowy wpis DECYZJA z naszym identyfikatorem.
 */
test("W01 - pelna sciezka happy path (decyzja zgodna z rekomendacja)", async ({ page }) => {
  await page.goto("/");

  const plik = path.resolve(__dirname, "../../dane/wnioski/W01.pdf");
  await page.locator('input[type="file"]').setInputFiles(plik);

  await page.waitForURL(/\/wnioski\/[0-9a-f-]+$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "W01.pdf" })).toBeVisible();

  // Polling co 2s az do CZEKA_NA_DECYZJE (atrapa modelu przetwarza chwile,
  // widok przechodzi z PRZETWARZANIE do formularza decyzji).
  await expect(page.getByRole("heading", { name: "Decyzja underwritera" })).toBeVisible({
    timeout: 30_000,
  });

  await expect(page.getByTestId("baner-ai")).toBeVisible();

  await page.getByRole("radio", { name: "Akceptacja" }).check();
  await expect(page.getByText(/Komentarz \(opcjonalny\)/)).toBeVisible();

  await page.getByLabel("Twój identyfikator").fill("e2e.w01");
  const przycisk = page.getByRole("button", { name: /zatwierdź decyzję/i });
  await expect(przycisk).toBeEnabled();
  await przycisk.click();

  await expect(page.getByText("Decyzja końcowa: AKCEPTACJA")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Zatwierdził:\s*e2e\.w01/)).toBeVisible();

  // Slad audytowy ma nowy wpis DECYZJA z naszym identyfikatorem.
  const sladAudytowy = page.locator("text=Ślad audytowy").locator("..");
  await expect(sladAudytowy.getByText("DECYZJA", { exact: true })).toBeVisible();
  await expect(sladAudytowy.getByText("e2e.w01", { exact: true })).toBeVisible();
});
