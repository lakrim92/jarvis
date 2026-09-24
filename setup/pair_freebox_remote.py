"""Appairage unique avec la Freebox Player (protocole Android TV Remote).

Usage : python setup/pair_freebox_remote.py <ip_du_player>
Le Player affiche un code a l'ecran ; ecris-le dans /tmp/atv_pin (ou tape-le ici si le terminal est interactif).
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from androidtvremote2 import AndroidTVRemote

SECRETS = Path(__file__).resolve().parent.parent / ".secrets"
CERT, KEY = SECRETS / "atv_cert.pem", SECRETS / "atv_key.pem"
PIN_FILE = Path("/tmp/atv_pin")


async def main(host: str):
    SECRETS.mkdir(exist_ok=True)
    remote = AndroidTVRemote("Jarvis", str(CERT), str(KEY), host)
    await remote.async_generate_cert_if_missing()
    os.chmod(KEY, 0o600)
    PIN_FILE.unlink(missing_ok=True)

    name, mac = await remote.async_get_name_and_mac()
    print(f"Appareil : {name} ({mac})", flush=True)
    await remote.async_start_pairing()
    print("CODE_AFFICHE_SUR_LA_TV : en attente du code dans /tmp/atv_pin", flush=True)

    deadline = time.time() + 300
    pin = None
    while time.time() < deadline:
        if PIN_FILE.exists():
            pin = PIN_FILE.read_text().strip()
            break
        await asyncio.sleep(1)
    if not pin:
        print("ECHEC : aucun code recu", flush=True)
        return
    await remote.async_finish_pairing(pin)
    PIN_FILE.unlink(missing_ok=True)

    await remote.async_connect()
    print("APPAIRAGE_OK", flush=True)
    print("is_on:", remote.is_on, "app:", remote.current_app, flush=True)
    (SECRETS / "freebox_player.json").write_text(json.dumps({"host": host, "name": name}))
    remote.disconnect()


asyncio.run(main(sys.argv[1]))
