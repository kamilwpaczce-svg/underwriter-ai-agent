import type { ZdarzenieAudytu } from "@/lib/typy";
import { formatujDateCzas } from "@/lib/formatowanie";

export default function AuditTrail({ zdarzenia }: { zdarzenia: ZdarzenieAudytu[] }) {
  return (
    <div className="space-y-2">
      <h3 className="text-base font-semibold">Ślad audytowy</h3>
      {zdarzenia.length === 0 ? (
        <p className="text-sm text-gray-500">Brak zdarzeń.</p>
      ) : (
        <ol className="space-y-2">
          {zdarzenia.map((zdarzenie) => {
            const odejscie = zdarzenie.dane?.odejscie_od_rekomendacji === true;
            return (
              <li
                key={zdarzenie.id}
                className="rounded border border-gray-200 p-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{formatujDateCzas(zdarzenie.czas)}</span>
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-semibold">
                    {zdarzenie.zdarzenie}
                  </span>
                  <span className="text-gray-600">{zdarzenie.kto ?? "system"}</span>
                  {zdarzenie.zdarzenie === "DECYZJA" && odejscie && (
                    <span
                      className="rounded bg-orange-100 px-1.5 py-0.5 text-xs font-semibold text-orange-900"
                      data-testid="audyt-odejscie"
                    >
                      odejście od rekomendacji
                    </span>
                  )}
                </div>
                {zdarzenie.dane && (
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-gray-500">
                      Szczegóły
                    </summary>
                    <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2 text-xs">
                      {JSON.stringify(zdarzenie.dane, null, 2)}
                    </pre>
                  </details>
                )}
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-xs text-gray-500">
        Zapis tylko do dopisywania — zdarzeń nie można edytować ani usuwać.
      </p>
    </div>
  );
}
