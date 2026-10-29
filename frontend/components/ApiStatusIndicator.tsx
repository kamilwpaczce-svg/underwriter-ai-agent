"use client";

import { useEffect, useState } from "react";
import { ADRES_API, sprawdzZdrowie } from "@/lib/api";

type Stan = "sprawdzanie" | "ok" | "blad";

/**
 * Wskaznik stanu API z /zdrowie. Napisany tak, by dalo sie go przetestowac
 * jednostkowo z mockiem fetch rzucajacym blad sieci (zamiennik testu e2e
 * "API wylaczone", ktorego celowo nie testujemy na zywym serwerze).
 */
export default function ApiStatusIndicator() {
  const [stan, setStan] = useState<Stan>("sprawdzanie");
  const [komunikat, setKomunikat] = useState<string | null>(null);

  useEffect(() => {
    let aktywny = true;
    sprawdzZdrowie()
      .then(() => {
        if (aktywny) {
          setStan("ok");
          setKomunikat(null);
        }
      })
      .catch((e: unknown) => {
        if (aktywny) {
          setStan("blad");
          setKomunikat(e instanceof Error ? e.message : "Nieznany błąd.");
        }
      });
    return () => {
      aktywny = false;
    };
  }, []);

  if (stan === "sprawdzanie") {
    return (
      <div className="text-sm text-gray-500" data-testid="api-status">
        Sprawdzanie połączenia z API…
      </div>
    );
  }

  if (stan === "blad") {
    return (
      <div
        className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800"
        data-testid="api-status"
        role="alert"
      >
        Brak połączenia z API pod adresem <strong>{ADRES_API}</strong>.
        {komunikat ? ` (${komunikat})` : ""} Upewnij się, że serwer działa.
      </div>
    );
  }

  return (
    <div
      className="rounded border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
      data-testid="api-status"
    >
      API dostępne ({ADRES_API})
    </div>
  );
}
