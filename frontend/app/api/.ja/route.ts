import { NextRequest } from "next/server";

/**
 * `GET /api/.ja` - tozsamosc uzytkownika widziana przez proxy, bez przekazywania do API.
 *
 * Gdy aplikacja dziala za Easy Auth (Container Apps), Easy Auth ustawia naglowek
 * `x-ms-client-principal-name` NA KAZDYM zadaniu i nadpisuje kazda wartosc podana przez
 * klienta - identyfikator z formularza decyzji (`DecisionForm`) jest wtedy i tak
 * ignorowany przez proxy (`app/api/[...sciezka]/route.ts`). Ten endpoint pozwala UI
 * pokazac to wprost: zwraca ten identyfikator (albo `null`, gdy Easy Auth nie jest
 * aktywny - dev lokalny), zeby formularz mogl wypelnic i zablokowac pole zamiast dawac
 * uzytkownikowi wrazenie, ze jego wpis cokolwiek zmienia.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const surowy = request.headers.get("x-ms-client-principal-name");
   
  const identyfikator = surowy !== null && /^[\x00-\x7F]*$/.test(surowy) ? surowy : null;
  return Response.json({ identyfikator });
}
