/**
 * Jedyny modul w aplikacji, ktory wywoluje `fetch`. Komponenty NIE woluja
 * fetch bezposrednio - tylko przez funkcje eksportowane stad. Etap 6: wywolania
 * ida do WLASNEGO originu (`/api/...`), ktory przechwytuje
 * `app/api/[...sciezka]/route.ts` i przekazuje do API po stronie serwera
 * (`API_URL_WEWNETRZNY`). Przegladarka nigdy nie mowi bezposrednio do API -
 * dzieki temu Easy Auth (ciasteczko domeny `uw-web`) dziala bez CORS.
 */

import type {
  Decyzja,
  UtworzWniosekOut,
  WniosekLista,
  WniosekSzczegoly,
  ZdarzenieAudytu,
  ZdrowieOut,
} from "./typy";

/** Zawsze wlasny origin - patrz docstring modulu. */
export const ADRES_API = "/api";

/**
 * Blad zawierajacy status HTTP i `detail` z odpowiedzi JSON (string albo
 * lista stringow, jak w /zdrowie), zeby UI moglo pokazac go doslownie.
 */
export class BladApi extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? BladApi.zbudujKomunikat(status, detail));
    this.name = "BladApi";
    this.status = status;
    this.detail = detail;
  }

  private static zbudujKomunikat(status: number, detail: unknown): string {
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.join("; ");
    }
    return `Blad API (status ${status}).`;
  }
}

async function obsluzOdpowiedz<T>(odpowiedz: Response): Promise<T> {
  if (!odpowiedz.ok) {
    let detail: unknown = null;
    try {
      const body = await odpowiedz.json();
      detail = body?.detail ?? null;
    } catch {
      // Odpowiedz bez cialo JSON - zostaw detail = null.
    }
    throw new BladApi(odpowiedz.status, detail);
  }
  if (odpowiedz.status === 204) {
    return undefined as T;
  }
  return (await odpowiedz.json()) as T;
}

/** GET /wnioski?status=&limit= */
export async function pobierzListeWnioskow(
  status?: string,
  limit?: number
): Promise<WniosekLista[]> {
  const parametry = new URLSearchParams();
  if (status) {
    parametry.set("status", status);
  }
  if (limit !== undefined) {
    parametry.set("limit", String(limit));
  }
  const query = parametry.toString();
  const odpowiedz = await fetch(
    `${ADRES_API}/wnioski${query ? `?${query}` : ""}`
  );
  return obsluzOdpowiedz<WniosekLista[]>(odpowiedz);
}

/** GET /wnioski/{id} */
export async function pobierzSzczegoly(id: string): Promise<WniosekSzczegoly> {
  const odpowiedz = await fetch(`${ADRES_API}/wnioski/${id}`);
  return obsluzOdpowiedz<WniosekSzczegoly>(odpowiedz);
}

/** POST /wnioski (multipart, pole "plik") */
export async function wgrajWniosek(plik: File): Promise<UtworzWniosekOut> {
  const formData = new FormData();
  formData.append("plik", plik);
  const odpowiedz = await fetch(`${ADRES_API}/wnioski`, {
    method: "POST",
    body: formData,
  });
  return obsluzOdpowiedz<UtworzWniosekOut>(odpowiedz);
}

/** URL surowych bajtow dokumentu - do <iframe>/<img>/linku, bez pobierania w JS. */
export function pobierzDokumentUrl(id: string): string {
  return `${ADRES_API}/wnioski/${id}/dokument`;
}

/** POST /wnioski/{id}/decyzja z naglowkiem X-Uzytkownik. */
export async function wyslijDecyzje(
  id: string,
  decyzja: Decyzja,
  komentarz: string | null,
  identyfikator: string
): Promise<WniosekSzczegoly> {
  const odpowiedz = await fetch(`${ADRES_API}/wnioski/${id}/decyzja`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Uzytkownik": identyfikator,
    },
    body: JSON.stringify({ decyzja, komentarz: komentarz || null }),
  });
  return obsluzOdpowiedz<WniosekSzczegoly>(odpowiedz);
}

/** GET /wnioski/{id}/audyt */
export async function pobierzAudyt(id: string): Promise<ZdarzenieAudytu[]> {
  const odpowiedz = await fetch(`${ADRES_API}/wnioski/${id}/audyt`);
  return obsluzOdpowiedz<ZdarzenieAudytu[]>(odpowiedz);
}

/** GET /zdrowie */
export async function sprawdzZdrowie(): Promise<ZdrowieOut> {
  const odpowiedz = await fetch(`${ADRES_API}/zdrowie`);
  return obsluzOdpowiedz<ZdrowieOut>(odpowiedz);
}

/**
 * GET /api/.ja - tozsamosc widziana przez proxy (Etap 6). Obslugiwane LOKALNIE przez
 * route handler Next.js (`app/api/.ja/route.ts`), nie przekazywane do API. Gdy aplikacja
 * dziala za Easy Auth, `identyfikator` jest wypelniony i formularz decyzji powinien
 * zablokowac recznie wpisywany identyfikator (i tak zostalby zignorowany przez proxy).
 */
export async function pobierzTozsamosc(): Promise<{ identyfikator: string | null }> {
  const odpowiedz = await fetch("/api/.ja");
  return obsluzOdpowiedz<{ identyfikator: string | null }>(odpowiedz);
}
