"""Jednorazowe wykonanie joba uw-dryf z nadpisana komenda kontenera (zasiew / sprzatanie w tescie alertow).

Obejscie: `az containerapp job start --args` interpretuje `--n` jako skrot wlasnych opcji (`--name`/`--no-wait`),
wiec komende podajemy przez REST (`jobs/{nazwa}/start` z szablonem kontenera). Image, env (z secretRef) i zasoby
sa kopiowane z definicji joba - zmienia sie tylko komenda. Wypisuje nazwe wykonania.

Uzycie (z laptopa, po `az login`):
    python infra/start_joba_dryfu.py -m ryzyko.zasiej_wejscia --n 300 --seed 11
    python infra/start_joba_dryfu.py -m ryzyko.zasiej_wejscia --sprzatnij
"""
import json
import subprocess
import sys
import tempfile

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
ID = ("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-underwriter-demo"
      "/providers/Microsoft.App/jobs/uw-dryf")


def az(*argumenty):
    wynik = subprocess.run([AZ, *argumenty], capture_output=True, text=True, encoding="utf-8")
    if wynik.returncode:
        sys.exit(wynik.stderr[-1500:])
    return wynik.stdout


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    kontener = json.loads(az("containerapp", "job", "show", "--ids", ID,
                             "--query", "properties.template.containers[0]", "-o", "json"))
    kontener = {k: kontener[k] for k in ("name", "image", "env", "resources")}
    kontener["resources"].pop("ephemeralStorage", None)
    kontener["command"] = ["python", *sys.argv[1:]]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as plik:
        json.dump({"containers": [kontener]}, plik)
    print(az("rest", "--method", "post", "--url", f"https://management.azure.com{ID}/start?api-version=2024-03-01",
             "--body", "@" + plik.name, "--query", "name", "-o", "tsv").strip())


if __name__ == "__main__":
    main()
