"""Find out which lever actually throttles the car.

Run this on the Home Assistant box **while a car is plugged in and charging**.
Every step restores what it changed, and the whole run is wrapped so an
interruption still puts the charger back the way it was.

    python3 ev_control_test.py            # measure, change nothing
    python3 ev_control_test.py --levers   # also try each lever in turn

Background: the CCU accepts OCPP charging profiles (200 OK, readable back) but
they do not bind the actual rate, because Ferroamp is the OCPP master. These
are different settings — the charger's own local configuration — so they may or
may not survive the master. That is what this measures.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

SETTLE_S = 90          # a charger takes ~1 min to act on a new limit
SAMPLE_S = 20
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def ha(path: str):
    tok = os.environ["SUPERVISOR_TOKEN"]
    req = urllib.request.Request("http://supervisor/core/api" + path,
                                 headers={"Authorization": f"Bearer {tok}"})
    return json.load(urllib.request.urlopen(req, timeout=25))


def state(entity: str, default=None):
    try:
        return ha("/states/" + entity)["state"]
    except Exception:
        return default


def num(entity: str, default=0.0) -> float:
    try:
        return float(state(entity))
    except (TypeError, ValueError):
        return default


class Ccu:
    def __init__(self):
        entries = json.load(open("/config/.storage/core.config_entries"))
        e = next(x for x in entries["data"]["entries"] if x["domain"] == "ctek_ccu")
        self.host = e["data"]["host"]
        self.user = e["data"]["username"]
        self.password = e["data"]["password"]
        self.cookie = None

    def call(self, path, body=None, method=None):
        req = urllib.request.Request(f"https://{self.host}{path}",
                                     method=method or ("POST" if body is not None else "GET"))
        if body is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(body).encode()
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            r = urllib.request.urlopen(req, context=CTX, timeout=15)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read().decode("utf-8", "replace")

    def __enter__(self):
        req = urllib.request.Request(f"https://{self.host}/api/status/login", method="POST")
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps({"username": self.user, "password": self.password}).encode()
        r = urllib.request.urlopen(req, context=CTX, timeout=15)
        self.cookie = r.headers.get("Set-Cookie", "").split(";")[0]
        return self

    def __exit__(self, *exc):
        # POST with no body: with {} the CCU logs out but resets the connection.
        self.call("/api/status/logout", method="POST")
        self.cookie = None

    def config(self) -> dict:
        s, b = self.call("/api/config/get")
        return json.loads(b) if s == 200 else {}

    def set_profile(self, key: str, value) -> tuple:
        """e.g. set_profile("default\\\\currentlimit", 6)."""
        return self.call("/api/config/update", {"profile": {key: str(value)}})


def measure(label: str) -> dict:
    """Average the interesting powers over one sampling window."""
    ev, batt, grid, solar = [], [], [], []
    end = time.monotonic() + SAMPLE_S
    while time.monotonic() < end:
        ev.append(num("sensor.ctek_charging_power"))
        batt.append(num("sensor.ferroamp_battery_power"))
        grid.append(num("sensor.ferroamp_grid_power"))
        solar.append(num("sensor.ferroamp_solar_power"))
        time.sleep(4)
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    r = {"label": label, "ev_w": avg(ev), "batt_w": avg(batt),
         "grid_w": avg(grid), "solar_w": avg(solar)}
    print(f"  {label:34s} bil {r['ev_w']:7.0f} W | batteri {r['batt_w']:8.0f} W"
          f" ({'urladdar' if r['batt_w'] > 50 else 'laddar' if r['batt_w'] < -50 else 'still'})"
          f" | nät {r['grid_w']:7.0f} W | sol {r['solar_w']:7.0f} W")
    return r


def main() -> int:
    print("== förutsättningar ==")
    outlet = state("sensor.ctek_outlet_1_state")
    print(f"  uttag: {outlet} | EMS ev_charging: {state('switch.ems_ev_charging')}"
          f" | plan: {state('sensor.ems_planned_mode')}")
    if outlet != "Charging":
        print("  AVBRYTER: ingen bil laddar just nu, testet mäter ingenting.")
        return 1

    base = measure("0. utgångsläge")
    if base["ev_w"] < 500:
        print("  AVBRYTER: laddeffekten är redan under 500 W.")
        return 1

    if "--levers" not in sys.argv:
        print("\nKör med --levers för att faktiskt prova spakarna.")
        return 0

    with Ccu() as ccu:
        cfg = ccu.config()
        before = (cfg.get("profile") or {}).get("default\\currentlimit")
        print(f"\n== spak 1: CCU:ns lokala strömgräns (nu {before!r}) ==")
        try:
            s, b = ccu.set_profile("default\\currentlimit", 6)
            print(f"  skrev 6 A -> HTTP {s} {b[:80]}")
            time.sleep(SETTLE_S)
            got = measure("1. lokal gräns 6 A")
            drop = base["ev_w"] - got["ev_w"]
            print(f"  => {'BITER' if drop > 800 else 'BITER INTE'} (skillnad {drop:.0f} W)")
        finally:
            if before is not None:
                ccu.set_profile("default\\currentlimit", before)
                print(f"  återställt till {before!r}")
            time.sleep(SETTLE_S)

    print("\n== spak 2: Ferroamps 'Begränsa import vid elbilsladdning och PowerShare' ==")
    print("  Slå på den i Ferroamp-appen nu, vänta två minuter, och kör sedan:")
    print("    python3 ev_control_test.py          (bara mätning)")
    print("  Tolkning:")
    print("    bilen sjunker, batteriet oförändrat  -> switchen räcker")
    print("    bilen oförändrad, batteriet urladdar -> hubben tar batteriet i stället;")
    print("      EMS-skyddet (0.28.0) ska då pinna urladdningen till noll åt oss")
    return 0


if __name__ == "__main__":
    sys.exit(main())
