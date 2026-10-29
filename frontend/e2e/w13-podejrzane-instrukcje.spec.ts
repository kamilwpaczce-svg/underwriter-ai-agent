import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * W13: zweryfikowany na zywym API (GET /wnioski/fc3dea22-4318-4c0a-96ed-732707bed90d)
 * jako dokument z podejrzane_instrukcje=true (wstrzykniete polecenia dla
 * modelu w tresci dokumentu). Sprawdzamy TYLKO widocznosc czerwonego banera
 * ostrzegawczego - nie dubllujemy tu testu przeplywu decyzji (ten jest w
 * w01/w03).
 */
test("W13 - baner podejrzanych instrukcji jest widoczny", async ({ page }) => {
  await page.goto("/");

  const plik = path.resolve(__dirname, "../../dane/wnioski/W13.pdf");
  await page.locator('input[type="file"]').setInputFiles(plik);

  await page.waitForURL(/\/wnioski\/[0-9a-f-]+$/, { timeout: 15_000 });

  const baner = page.getByTestId("baner-podejrzane-instrukcje");
  await expect(baner).toBeVisible({ timeout: 30_000 });
  await expect(baner).toContainText(/wstrzykni|polece/i);
});
