"""Fikcyjne zdjecia szkod Z01..Z12 (Etap 23) przez fal.ai flux/dev.

Kazde zdjecie odpowiada polu `przyczyna` przypadku z przypadki_szkody.py. Zdjecia sa
generowane z promptu, wiec sa "latwiejsze" niz prawdziwe zdjecia od klientow - to
ograniczenie ewaluacji, nie jej wynik.

Uruchomienie (klucz z ~/.fal_key, nigdy nie wypisywany):
    FAL_KEY=$(tr -d '\\r\\n' < ~/.fal_key) python -m generator.zdjecia_szkod [Z01 Z05 ...]
Koszt: flux/dev 0,025 USD/MP, 1024x768 = 1 MP -> ok. 0,30 USD za komplet.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent / "dane" / "zdjecia_szkod"
MODEL = "fal-ai/flux/dev"
SEED = 2310
# Z01, Z03, Z06, Z07 poprawione 27.10 (pierwsza wersja nie pokazywala zgloszonej przyczyny), inny seed
# Z03 i Z06 ostatecznie z nano-banana (generator/zdjecia_szkod_nb.py) - flux dorysowywal rdze
SEED_POPRAWKI = {"Z01": 4417, "Z03": 4417, "Z06": 4417, "Z07": 4417}

STYL = (
    "Amateur smartphone photo taken by a small business owner for an insurance claim, "
    "Poland, natural light, realistic, slightly imperfect framing, no people, no text, no logos, no watermark. "
)

PROMPTY = {
    "Z01": "Bakery production hall destroyed by fire: completely charred black ceiling and collapsed roof beams, thick black soot on all walls, burnt melted electrical wiring and a scorched electrical panel next to an industrial bread oven, burnt trays and debris on a wet floor after firefighting, strong fire damage everywhere.",
    "Z02": "Printing workshop floor flooded with clean water around an offset printing machine, "
           "a burst water pipe on the wall still dripping, wet control cabinet of the machine, puddles reflecting ceiling lights.",
    "Z03": "Close-up of a clean modern electrical control cabinet of a woodworking panel saw, one circuit board with a black burnt scorch mark, exploded capacitor and melted plastic connector after a power surge, fresh soot streaks above terminals, no rust, otherwise clean new equipment.",
    "Z04": "Empty outdoor unfenced yard in front of a warehouse, gravel ground with rectangular marks and "
           "a few broken wooden pallets where pallets of paper used to stand, warehouse door closed and intact, overcast day.",
    "Z05": "CNC lathe in a workshop with heavy orange-brown rust on the guideways and metal surfaces, "
           "long-term water stains and dripping marks from a leaking roof above, mold spots on the ceiling, a bucket under the leak.",
    "Z06": "Industrial laundry room, electric motor removed from a commercial washing machine lying on a workbench, motor housing opened showing dark brown burnt copper windings with melted insulation from overheating, the machine and room clean and dry, no water, no rust, no fire elsewhere.",
    "Z07": "Night photo with flash of the forced-open front glass and metal door of a small electronics repair shop: door pried open, bent frame, broken lock hanging, splintered wood and shards of broken glass on the ground, crowbar marks, inside an empty workbench with loose cables where laptops were stolen.",
    "Z08": "Burnt stock in a garden center storage room: charred shelves, melted plastic bags of fertilizer, "
           "burnt seed packets and blackened garden tools, ash on the floor, soot-covered walls.",
    "Z09": "Small office room after water damage from a burst heating pipe: soaked carpet, water stains rising on the "
           "lower part of the walls, wet desks, a radiator pipe with a visible crack, puddle on the floor.",
    "Z10": "Paper stock warehouse after sprinkler system discharge: soaked and swollen reams of paper on pallets, "
           "water dripping from ceiling sprinkler heads, wet concrete floor, collapsed wet cardboard boxes.",
    "Z11": "High-bay warehouse with part of the roof torn off by a storm: missing roof panels, open sky visible, "
           "bent metal sheets hanging, debris and rainwater on the racks below, broken roofing on the ground outside.",
    "Z12": "Back room of a small pastry shop after a fire started in an oven: burnt commercial oven with blackened door, "
           "scorched refrigerated display cabinet next to it, soot on tiles and ceiling.",
}


def generuj(kod: str, klucz: str) -> Path:
    body = json.dumps({
        "prompt": STYL + PROMPTY[kod],
        "image_size": {"width": 1024, "height": 768},
        "num_images": 1,
        "seed": SEED_POPRAWKI.get(kod, SEED),
        "enable_safety_checker": True,
    }).encode()
    req = urllib.request.Request(
        f"https://fal.run/{MODEL}", data=body, method="POST",
        headers={"Authorization": f"Key {klucz}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            wynik = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{kod}: HTTP {e.code} {e.read()[:300]!r}")
    url = wynik["images"][0]["url"]
    cel = KATALOG / f"{kod}.jpg"
    urllib.request.urlretrieve(url, cel)
    return cel


def main() -> None:
    klucz = os.environ.get("FAL_KEY", "").strip()
    if not klucz:
        raise SystemExit("Brak FAL_KEY")
    KATALOG.mkdir(parents=True, exist_ok=True)
    kody = sys.argv[1:] or list(PROMPTY)
    for kod in kody:
        cel = generuj(kod, klucz)
        print(f"{kod} -> {cel.name} ({cel.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
