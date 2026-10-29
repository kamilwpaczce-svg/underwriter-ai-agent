import type { Pola } from "@/lib/typy";
import { formatujAdres, formatujBoolean, formatujKwote, formatujNullable } from "@/lib/formatowanie";

const ETYKIETY: Array<{ klucz: keyof Pola; etykieta: string }> = [
  { klucz: "nazwa_firmy", etykieta: "Nazwa firmy" },
  { klucz: "nip", etykieta: "NIP" },
  { klucz: "adres", etykieta: "Adres" },
  { klucz: "pkd", etykieta: "PKD" },
  { klucz: "branza", etykieta: "Branża" },
  { klucz: "rodzaj_konstrukcji", etykieta: "Rodzaj konstrukcji" },
  { klucz: "rok_budowy", etykieta: "Rok budowy" },
  { klucz: "su_budynki", etykieta: "Suma ubezpieczenia — budynki" },
  { klucz: "su_maszyny", etykieta: "Suma ubezpieczenia — maszyny" },
  { klucz: "su_zapasy", etykieta: "Suma ubezpieczenia — zapasy" },
  { klucz: "tryskacze", etykieta: "Tryskacze" },
  { klucz: "ssp", etykieta: "SSP (sygnalizacja pożaru)" },
  { klucz: "strefa_powodziowa", etykieta: "Strefa powodziowa" },
  { klucz: "okres_od", etykieta: "Okres ubezpieczenia od" },
  { klucz: "okres_do", etykieta: "Okres ubezpieczenia do" },
  { klucz: "data_wniosku", etykieta: "Data wniosku" },
  { klucz: "broker", etykieta: "Broker" },
  { klucz: "uwagi", etykieta: "Uwagi" },
];

const POLA_KWOTOWE = new Set<keyof Pola>(["su_budynki", "su_maszyny", "su_zapasy"]);
const POLA_BOOLEAN = new Set<keyof Pola>(["tryskacze", "ssp", "strefa_powodziowa"]);

function sformatujWartosc(klucz: keyof Pola, pola: Pola): string {
  const wartosc = pola[klucz];
  if (klucz === "adres") {
    return formatujAdres(pola.adres);
  }
  if (POLA_KWOTOWE.has(klucz)) {
    return formatujKwote(wartosc as number | null);
  }
  if (POLA_BOOLEAN.has(klucz)) {
    return formatujBoolean(wartosc as boolean | null);
  }
  return formatujNullable(wartosc as string | number | null);
}

export default function PolaTable({ pola }: { pola: Pola }) {
  const szkody = pola.szkody_3_lata ?? [];
  return (
    <div className="space-y-4">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {ETYKIETY.map(({ klucz, etykieta }) => (
            <tr key={klucz} className="border-b border-gray-200">
              <th className="w-1/3 py-1 pr-4 text-left font-medium text-gray-600">
                {etykieta}
              </th>
              <td className="py-1">{sformatujWartosc(klucz, pola)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <h3 className="mb-1 text-sm font-semibold">Szkody w ostatnich 3 latach</h3>
        {szkody.length === 0 ? (
          <p className="text-sm text-gray-500">Brak zgłoszonych szkód.</p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-300 text-left text-gray-600">
                <th className="py-1 pr-4">Rok</th>
                <th className="py-1 pr-4">Przyczyna</th>
                <th className="py-1">Kwota</th>
              </tr>
            </thead>
            <tbody>
              {szkody.map((szkoda, indeks) => (
                <tr key={indeks} className="border-b border-gray-100">
                  <td className="py-1 pr-4">{formatujNullable(szkoda.rok)}</td>
                  <td className="py-1 pr-4">{formatujNullable(szkoda.przyczyna)}</td>
                  <td className="py-1">{formatujKwote(szkoda.kwota)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
