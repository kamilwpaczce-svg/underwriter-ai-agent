"""Regeneracja Z03/Z06 przez fal-ai/nano-banana (0,0398 USD/obraz) -> ZNN_nb.jpg.

Flux/dev uparcie dorysowywal rdze przy przepieciu i przegrzanym silniku (gpt-5-mini ocenial
je jako korozje, czyli zla etykieta, nie trudny przypadek). Wynik 1184x864 recznie skalowany
do 1024x768 jako ZNN.jpg; stare wersje flux zostaly jako ZNN_flux_rdza.jpg.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

KAT = Path(__file__).resolve().parent.parent / "dane" / "zdjecia_szkod"
STYL = ("Amateur smartphone photo taken by a small business owner for an insurance claim, Poland, "
        "natural light, realistic, no people, no text, no logos. ")
PROMPTY = {
    "Z03": "Open electrical control cabinet of a modern woodworking panel saw, everything inside clean, new, "
           "shiny and grey-white. One green circuit board in the center has a fresh black burn mark, a bulged "
           "and burst capacitor and a melted plastic connector, with a thin streak of black soot above it, "
           "typical damage after a power surge. All metal is clean and unpainted steel or galvanized, "
           "absolutely no rust, no corrosion, no water, no dirt.",
    "Z06": "Electric motor from a commercial washing machine lying on a clean white workbench in a modern "
           "laundry room. The motor housing is opened and shows the copper windings: they are dark brown and "
           "black from overheating, with melted and cracked insulation varnish and a small burnt spot. The "
           "motor casing is clean painted metal, absolutely no rust, no corrosion, no water, no fire around.",
}

klucz = os.environ["FAL_KEY"].strip()
for kod in sys.argv[1:] or list(PROMPTY):
    body = json.dumps({"prompt": STYL + PROMPTY[kod], "num_images": 1, "aspect_ratio": "4:3",
                       "output_format": "jpeg"}).encode()
    req = urllib.request.Request("https://fal.run/fal-ai/nano-banana", data=body, method="POST",
                                 headers={"Authorization": f"Key {klucz}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        url = json.load(r)["images"][0]["url"]
    cel = KAT / f"{kod}_nb.jpg"
    urllib.request.urlretrieve(url, cel)
    print(kod, "->", cel.name, cel.stat().st_size // 1024, "KB")
