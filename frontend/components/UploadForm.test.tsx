import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UploadForm from "./UploadForm";
import * as api from "@/lib/api";

describe("UploadForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("odrzuca plik z niedozwolonym rozszerzeniem (drag&drop) BEZ wywolania API", async () => {
    // Uzywamy drop zamiast user.upload() na <input accept=...>: user-event
    // respektuje atrybut accept (jak natywny selektor plikow) i w ogole nie
    // odpalilby change dla .txt. Przeciagniecie pliku (drag&drop) NIE jest
    // filtrowane przez accept w przegladarce, wiec to realistyczny sposob na
    // sprawdzenie walidacji klienta dla niedozwolonego rozszerzenia.
    const spyWgraj = vi.spyOn(api, "wgrajWniosek");
    render(<UploadForm onSukces={vi.fn()} />);

    const plik = new File(["tresc"], "notatka.txt", { type: "text/plain" });
    const strefa = screen.getByTestId("strefa-upuszczania");
    fireEvent.drop(strefa, { dataTransfer: { files: [plik] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/pdf|jpg|jpeg|eml|rozszerzen/i);
    expect(spyWgraj).not.toHaveBeenCalled();
  });

  it("odrzuca plik wiekszy niz 10 MB BEZ wywolania API", async () => {
    const spyWgraj = vi.spyOn(api, "wgrajWniosek");
    const user = userEvent.setup();
    render(<UploadForm onSukces={vi.fn()} />);

    const zaDuzy = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "wniosek.pdf", {
      type: "application/pdf",
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, zaDuzy);

    expect(await screen.findByRole("alert")).toHaveTextContent(/10 ?MB|rozmiar/i);
    expect(spyWgraj).not.toHaveBeenCalled();
  });

  it("po udanym uploadzie poprawnego pliku wywoluje onSukces z id", async () => {
    vi.spyOn(api, "wgrajWniosek").mockResolvedValue({
      id: "abc-123",
      status: "PRZETWARZANIE",
    });
    const onSukces = vi.fn();
    const user = userEvent.setup();
    render(<UploadForm onSukces={onSukces} />);

    const plik = new File(["%PDF-1.4"], "wniosek.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, plik);

    await waitFor(() => expect(onSukces).toHaveBeenCalledWith("abc-123"));
  });

  it("pokazuje literalny blad z API (BladApi, detail string) bez wywolania onSukces", async () => {
    vi.spyOn(api, "wgrajWniosek").mockRejectedValue(
      new api.BladApi(415, "Niedozwolony typ pliku.")
    );
    const onSukces = vi.fn();
    const user = userEvent.setup();
    render(<UploadForm onSukces={onSukces} />);

    const plik = new File(["%PDF-1.4"], "wniosek.pdf", { type: "application/pdf" });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, plik);

    expect(await screen.findByRole("alert")).toHaveTextContent("Niedozwolony typ pliku.");
    expect(onSukces).not.toHaveBeenCalled();
  });
});
