import { Suspense } from "react";
import SzczegolyWniosku from "./SzczegolyWniosku";

/**
 * Serwerowy wrapper: `useParams()` w kliencie wymaga granicy <Suspense>,
 * zeby Next.js (Cache Components) mogl zbudowac statyczna powloke strony.
 * Cala logika i fetch danych siedza w komponencie klienckim ponizej.
 */
export default function Page() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-500">Ładowanie…</div>}>
      <SzczegolyWniosku />
    </Suspense>
  );
}
