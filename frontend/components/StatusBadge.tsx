const KOLORY: Record<string, string> = {
  PRZETWARZANIE: "bg-blue-100 text-blue-800 border-blue-300",
  CZEKA_NA_DECYZJE: "bg-amber-100 text-amber-800 border-amber-300",
  ZAKONCZONY: "bg-green-100 text-green-800 border-green-300",
  INNY_DOKUMENT: "bg-gray-100 text-gray-800 border-gray-300",
  BLAD: "bg-red-100 text-red-800 border-red-300",
};

const ETYKIETY: Record<string, string> = {
  PRZETWARZANIE: "Przetwarzanie",
  CZEKA_NA_DECYZJE: "Czeka na decyzję",
  ZAKONCZONY: "Zakończony",
  INNY_DOKUMENT: "Inny dokument",
  BLAD: "Błąd",
};

export default function StatusBadge({ status }: { status: string }) {
  const klasa = KOLORY[status] ?? "bg-gray-100 text-gray-800 border-gray-300";
  const etykieta = ETYKIETY[status] ?? status;
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${klasa}`}
    >
      {etykieta}
    </span>
  );
}
