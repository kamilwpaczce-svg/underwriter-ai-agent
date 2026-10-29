import type { Podsumowanie, WniosekSzczegoly } from "@/lib/typy";
import PolaTable from "./PolaTable";

interface Props {
  podsumowanie: Podsumowanie;
  wniosek: WniosekSzczegoly;
}

/**
 * Prezentacyjna sekcja analizy wniosku: banery (AI, podejrzane instrukcje),
 * tabela pol, problemy walidacji, karty rekomendacji LLM vs silnik regul,
 * flaga rozbieznosci, przebieg agenta (log_wezlow + sumy). Komponent czysto
 * prezentacyjny (bez fetch) - latwy do przetestowania z danymi testowymi.
 */
export default function SekcjaAnaliz({ podsumowanie, wniosek }: Props) {
  const { pola, rekomendacja, decyzja_silnika, zgodnosc, podejrzane_instrukcje, blad } = podsumowanie;
  // null, gdy graf ominal waliduj (blad klasyfikacji/ekstrakcji) - patrz agent/graf.py.
  const problemy_walidacji = podsumowanie.problemy_walidacji ?? [];

  return (
    <div className="space-y-4">
      {blad && (
        <div
          className="rounded border-2 border-red-500 bg-red-100 px-3 py-2 text-sm text-red-900"
          role="alert"
          data-testid="blad-agenta"
        >
          <span className="font-semibold">Błąd agenta:</span> {blad}
        </div>
      )}

      {rekomendacja && (
        <div
          className="rounded border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900"
          data-testid="baner-ai"
        >
          Rekomendacja wygenerowana przez model AI. Decyzję podejmuje underwriter.
        </div>
      )}

      {podejrzane_instrukcje && (
        <div
          className="rounded border-2 border-red-500 bg-red-100 px-3 py-2 text-sm font-semibold text-red-900"
          role="alert"
          data-testid="baner-podejrzane-instrukcje"
        >
          Uwaga: dokument zawiera treść przypominającą polecenia dla modelu AI
          (próba wstrzyknięcia poleceń). Rekomendację należy traktować z ostrożnością.
        </div>
      )}

      {problemy_walidacji.length > 0 && (
        <div
          className="rounded border border-yellow-400 bg-yellow-50 px-3 py-2 text-sm text-yellow-900"
          data-testid="problemy-walidacji"
        >
          <p className="mb-1 font-semibold">Problemy walidacji:</p>
          <ul className="list-disc pl-5">
            {problemy_walidacji.map((problem, indeks) => (
              <li key={indeks}>{problem}</li>
            ))}
          </ul>
        </div>
      )}

      {pola && (
        <div>
          <h2 className="mb-2 text-base font-semibold">Pola wniosku</h2>
          <PolaTable pola={pola} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded border border-gray-300 p-3">
          <h3 className="mb-2 text-sm font-semibold">Rekomendacja LLM</h3>
          {rekomendacja ? (
            <div className="space-y-1 text-sm">
              <p>
                <span className="font-medium">Decyzja:</span> {rekomendacja.decyzja}
              </p>
              <p>
                <span className="font-medium">Reguły:</span>{" "}
                {rekomendacja.reguly.length > 0 ? rekomendacja.reguly.join(", ") : "brak"}
              </p>
              {rekomendacja.uzasadnienie.length > 0 && (
                <ul className="list-disc pl-5">
                  {rekomendacja.uzasadnienie.map((u, indeks) => (
                    <li key={indeks}>
                      <span className="font-medium">{u.regula}:</span> {u.tekst}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-500">Brak rekomendacji.</p>
          )}
        </div>

        <div className="rounded border border-gray-300 p-3">
          <h3 className="mb-2 text-sm font-semibold">Silnik reguł</h3>
          {decyzja_silnika ? (
            <div className="space-y-1 text-sm">
              <p>
                <span className="font-medium">Decyzja:</span> {decyzja_silnika.decyzja}
              </p>
              <p>
                <span className="font-medium">Reguły:</span>{" "}
                {decyzja_silnika.reguly.length > 0 ? decyzja_silnika.reguly.join(", ") : "brak"}
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-500">Brak decyzji silnika.</p>
          )}
        </div>
      </div>

      {zgodnosc === false && (
        <div
          className="rounded border-2 border-orange-400 bg-orange-50 px-3 py-2 text-sm font-semibold text-orange-900"
          data-testid="flaga-rozbieznosci"
        >
          Rozbieżność LLM i silnika reguł
        </div>
      )}

      {wniosek.log_wezlow && wniosek.log_wezlow.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Przebieg agenta</h3>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-300 text-left text-gray-600">
                <th className="py-1 pr-4">Węzeł</th>
                <th className="py-1 pr-4">Czas (ms)</th>
                <th className="py-1 pr-4">Tokeny we</th>
                <th className="py-1">Tokeny wy</th>
              </tr>
            </thead>
            <tbody>
              {wniosek.log_wezlow.map((wezel, indeks) => (
                <tr key={indeks} className="border-b border-gray-100">
                  <td className="py-1 pr-4">{wezel.wezel}</td>
                  <td className="py-1 pr-4">{wezel.czas_ms}</td>
                  <td className="py-1 pr-4">{wezel.tokeny_we ?? "—"}</td>
                  <td className="py-1">{wezel.tokeny_wy ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-sm text-gray-600">
            Łącznie: wywołania LLM: {wniosek.wywolania_llm ?? "—"}, tokeny wejściowe:{" "}
            {wniosek.tokeny_we ?? "—"}, tokeny wyjściowe: {wniosek.tokeny_wy ?? "—"}.
          </p>
        </div>
      )}
    </div>
  );
}
