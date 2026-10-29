import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * W03: rekomendacja LLM i decyzja silnika zweryfikowane na zywym API jako
 * obie "SKIEROWANIE" (GET /wnioski/3f1567a5-fb0d-479e-b2b9-8bb07124d0d2).
 * Wybieramy underwriterem AKCEPTACJA - rozni sie od obu, wiec komentarz jest
 * WYMAGANY (serwerowa logika z api/trasy.py:177) i przycisk ma byc
 * zablokowany, dopoki go nie wpiszemy. Po zatwierdzeniu audyt powinien miec
 * odejscie_od_rekomendacji:true (wyswietlane jako baner "odejście od
 * rekomendacji" w AuditTrail).
 */
test("W03 - odejscie od rekomendacji wymaga komentarza", async ({ page }) => {
  await page.goto("/");

  const plik = path.resolve(__dirname, "../../dane/wnioski/W03.pdf");
  await page.locator('input[type="file"]').setInputFiles(plik);

  await page.waitForURL(/\/wnioski\/[0-9a-f-]+$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Decyzja underwritera" })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("radio", { name: "Akceptacja" }).check();
  await expect(page.getByText(/Komentarz \(wymagany/)).toBeVisible();

  const przycisk = page.getByRole("button", { name: /zatwierdź decyzję/i });
  await page.getByLabel("Twój identyfikator").fill("e2e.w03");
  await expect(przycisk).toBeDisabled();

  await page
    .getByLabel(/Komentarz/)
    .fill("Underwriter odstepuje od rekomendacji - test e2e.");
  await expect(przycisk).toBeEnabled();
  await przycisk.click();

  await expect(page.getByText("Decyzja końcowa:")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Zatwierdził:\s*e2e\.w03/)).toBeVisible();

  const sladAudytowy = page.locator("text=Ślad audytowy").locator("..");
  await expect(sladAudytowy.getByTestId("audyt-odejscie").first()).toBeVisible();
});
