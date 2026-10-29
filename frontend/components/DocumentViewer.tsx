import { pobierzDokumentUrl } from "@/lib/api";

interface Props {
  id: string;
  typMime: string;
  nazwaPliku: string;
}

/** PDF w <iframe>, JPG w <img>, .eml - tylko link "Pobierz plik" (bez renderowania). */
export default function DocumentViewer({ id, typMime, nazwaPliku }: Props) {
  const url = pobierzDokumentUrl(id);

  if (typMime === "application/pdf") {
    return (
      <iframe
        src={url}
        title={nazwaPliku}
        className="h-[80vh] w-full rounded border border-gray-300"
      />
    );
  }

  if (typMime === "image/jpeg" || typMime === "image/png") {
    // eslint-disable-next-line @next/next/no-img-element -- adres pochodzi z API, nie z Next Image loadera
    return <img src={url} alt={nazwaPliku} className="w-full rounded border border-gray-300" />;
  }

  return (
    <div className="rounded border border-gray-300 p-4 text-sm">
      <p className="mb-2">
        Podgląd niedostępny dla tego typu pliku ({typMime}).
      </p>
      <a href={url} download={nazwaPliku} className="text-blue-700 underline">
        Pobierz plik
      </a>
    </div>
  );
}
