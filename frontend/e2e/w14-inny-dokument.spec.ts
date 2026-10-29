import { test, expect } from "@playwright/test";
import path from "node:path";

/**
 * W14: zweryfikowany na zywym API (GET /wnioski/ff3cfc7c-8173-4d10-b866-6163b23d5b9c)
 * jako status INNY_DOKUMENT (nie-wniosek, "podsumowanie": null, 2 wpisy w
 * log_wezlow). Sprawdzamy, ze UI pokazuje informacje o tym statusie i NIE
 * renderuje formularza decyzji.
 */
test("W14 - status INNY_DOKUMENT bez formularza decyzji", async ({ page }) => {
  await page.goto("/");

  const plik = path.resolve(__dirname, "../../dane/wnioski/W14.pdf");
  await page.locator('input[type="file"]').setInputFiles(plik);

  await page.waitForURL(/\/wnioski\/[0-9a-f-]+$/, { timeout: 15_000 });

  await expect(page.getByText("nie jest wnioskiem ubezpieczeniowym")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("heading", { name: "Decyzja underwritera" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: /zatwierdź decyzję/i })).not.toBeVisible();
});
