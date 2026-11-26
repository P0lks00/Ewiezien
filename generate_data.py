#!/usr/bin/env python3
"""
Generator danych testowych dla bazy danych Systemu Ewidencji Zakładu Karnego (PostgreSQL).

Pobiera dane zewnętrzne z publicznych API (bez kluczy API, tylko biblioteka standardowa):
- Dane osobowe (imiona, nazwiska, płeć, daty urodzenia):
    * domyślnie: FakerAPI v2 (https://fakerapi.it/api/v2/persons?_locale=pl_PL)
    * alternatywnie / fallback: RandomUser API (https://randomuser.me/api/)
- Lista polskich sądów powszechnych (Sądy Rejonowe / Okręgowe / Apelacyjne):
    * SAOS API — System Analizy Orzeczeń Sądowych
      (https://www.saos.org.pl/api/dump/commonCourts)

Zgodny ze schematem i warunkami integralności z dokumentu Bazy-danych-projekt-1.pdf:
- Tabele: cele, personel, wiezniowie, wyroki, przydzialy_cel, widzenia, incydenty
- Wszystkie ograniczenia CHECK, UNIQUE, NOT NULL oraz klucze obce
- Zgodność z wyzwalaczami (pojemność celi, jeden aktywny przydział, blokada dodawania
  widzeń/przydziałów dla nieaktywnych więźniów).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Konfiguracja domenowa zakładu karnego (wartości słownikowe / reguły biznesowe)
# ---------------------------------------------------------------------------

STOPNIE_SW = [
    "szeregowy",
    "starszy szeregowy",
    "kapral",
    "starszy kapral",
    "plutonowy",
    "sierżant",
    "starszy sierżant",
    "młodszy chorąży",
    "chorąży",
    "starszy chorąży",
    "podporucznik",
    "porucznik",
    "kapitan",
    "major",
    "podpułkownik",
]

# (artykuł, minimalna długość kary w dniach, maksymalna długość kary w dniach)
ARTYKULY_KK: list[tuple[str, int, int]] = [
    ("art. 148 § 1 kk", 2920, 9125),
    ("art. 156 § 1 kk", 1095, 3650),
    ("art. 157 § 1 kk", 180, 1460),
    ("art. 158 § 1 kk", 180, 1095),
    ("art. 177 § 2 kk", 365, 2555),
    ("art. 178a § 1 kk", 90, 730),
    ("art. 190 § 1 kk", 90, 540),
    ("art. 207 § 1 kk", 180, 1460),
    ("art. 209 § 1 kk", 90, 365),
    ("art. 222 § 1 kk", 180, 900),
    ("art. 244 kk", 180, 1095),
    ("art. 258 § 1 kk", 365, 1825),
    ("art. 270 § 1 kk", 180, 1095),
    ("art. 278 § 1 kk", 180, 1460),
    ("art. 279 § 1 kk", 365, 2920),
    ("art. 280 § 1 kk", 730, 4380),
    ("art. 286 § 1 kk", 365, 2555),
    ("art. 288 § 1 kk", 180, 1095),
    ("art. 291 § 1 kk", 180, 1460),
    ("art. 62 ust. 1 u.p.n.", 180, 1095),
    ("art. 56 ust. 3 u.p.n.", 730, 3650),
]

RELACJE_ODWIEDZAJACYCH = [
    "matka", "ojciec", "żona", "mąż", "partnerka", "partner",
    "brat", "siostra", "syn", "córka", "adwokat", "babcia",
    "dziadek", "wujek", "ciocia", "znajomy", "kurator",
]

OPISY_INCYDENTOW: dict[str, list[str]] = {
    "bojka": [
        "Sprzeczka podczas spaceru na spacerniaku przerodziła się w bójkę ze współosadzonym.",
        "Uderzenie współosadzonego w celi mieszkalnej podczas wydawania posiłku.",
        "Udział w bójce grupowej na świetlicy oddziału; szybka interwencja oddziałowych.",
        "Agresywne zachowanie i szarpanina z innym osadzonym w trakcie kolejki do łaźni.",
        "Pobicie współosadzonego na tle konfliktu osobistego, skierowano do ambulatorium.",
    ],
    "kontrabanda": [
        "Podczas kontroli osobistej ujawniono ukryty telefon komórkowy z kartą SIM.",
        "W trakcie przeszukania celi znaleziono nielegalny alkohol fermentowany w butelce.",
        "Ujawnienie substancji psychoaktywnych ukrytych w paczce higienicznej.",
        "Znalezienie prowizorycznego ostrego narzędzia schowanego w materacu.",
        "Przechwycenie ładowarki i słuchawek przekazanych nielegalnie podczas widzenia.",
    ],
    "proba_ucieczki": [
        "Próba sforsowania ogrodzenia zewnętrznego podczas powrotu ze spaceru.",
        "Uszkodzenie kraty okiennej w celi przy użyciu przemyconego brzeszczotu.",
        "Próba samowolnego oddalenia się podczas konwoju na rozprawę sądową.",
        "Próba ukrycia się w pojeździe dostawczym na terenie strefy gospodarczej.",
    ],
    "nagroda": [
        "Wyróżnienie za wzorowe zachowanie i aktywny udział w pracach porządkowych.",
        "Nagroda regulaminowa w postaci dodatkowego widzenia za postępy w resocjalizacji.",
        "Pochwała dyrektora za ukończenie kursu zawodowego i pomoc w bibliotece.",
        "Przyznanie dłuższego widzenia za bezkonfliktowe funkcjonowanie w oddziale.",
        "Wyróżnienie za zaangażowanie w zajęcia terapeutyczne i sportowe.",
    ],
    "inne": [
        "Odmowa wykonania polecenia funkcjonariusza podczas apelu porządkowego.",
        "Celowe uszkodzenie wyposażenia celi (złamane krzesło i uszkodzony zlew).",
        "Wulgarne znieważenie funkcjonariusza służby więziennej podczas kontroli.",
        "Samowolna zmiana miejsca spania i zakłócanie ciszy nocnej w oddziale.",
        "Odmowa przyjmowania posiłków — wszczęto obserwację psychologiczną i lekarską.",
    ],
}

BLOKI_KONFIG: list[tuple[str, str, int, int]] = [
    ("A", "otwarty", 4, 10),
    ("B", "polotwarty", 3, 8),
    ("C", "zamkniety", 2, 6),
    ("D", "zamkniety", 2, 4),
    ("IZ", "izolatka", 1, 2),
]

STATUSY_WIEZNIOW = ["osadzony", "zwolniony", "przeniesiony", "zbiegly", "zmarly"]
STATUSY_WAGI = [0.68, 0.18, 0.08, 0.03, 0.03]


# ---------------------------------------------------------------------------
# Klient zewnętrznych API (stdlib urllib)
# ---------------------------------------------------------------------------

@dataclass
class OsobaAPI:
    imie: str
    nazwisko: str
    plec: str  # "M" lub "K"
    data_urodzenia: date | None


def http_get_json(url: str, timeout: int = 15) -> Any:
    """Wykonuje żądanie HTTP GET i parsuje odpowiedź JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ZakladKarnyDataGenerator/1.0 (Python urllib)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def dopasuj_nazwisko_do_plci(nazwisko: str, plec: str) -> str:
    """Dopasowuje końcówki polskich nazwisk (-ski/-ska, -cki/-cka, -dzki/-dzka) do płci."""
    if plec == "K":
        if nazwisko.endswith(("ski", "cki", "dzki")):
            return nazwisko[:-1] + "a"
    elif plec == "M":
        if nazwisko.endswith(("ska", "cka", "dzka")):
            return nazwisko[:-1] + "i"
    return nazwisko


def pobierz_osoby_fakerapi(
    liczba: int,
    seed: int,
    timeout: int = 15,
) -> list[OsobaAPI]:
    """
    Pobiera polskie dane osobowe z FakerAPI v2:
    https://fakerapi.it/api/v2/persons?_locale=pl_PL&_quantity=...&_seed=...
    """
    osoby: list[OsobaAPI] = []
    pozostalo = liczba
    partia_nr = 0

    while pozostalo > 0:
        batch = min(pozostalo, 1000)
        params = urllib.parse.urlencode({
            "_locale": "pl_PL",
            "_quantity": batch,
            "_seed": seed + partia_nr,
        })
        url = f"https://fakerapi.it/api/v2/persons?{params}"
        payload = http_get_json(url, timeout=timeout)
        rekordy = payload.get("data", [])
        if not rekordy:
            raise RuntimeError("FakerAPI zwróciło pustą listę osób.")

        for item in rekordy:
            imie = str(item.get("firstname", "")).strip()[:50]
            nazwisko = str(item.get("lastname", "")).strip()[:50]
            if not imie or not nazwisko:
                continue
            plec_raw = str(item.get("gender", "male")).lower()
            plec = "K" if plec_raw == "female" else "M"
            nazwisko = dopasuj_nazwisko_do_plci(nazwisko, plec)
            bday: date | None = None
            bday_raw = item.get("birthday")
            if bday_raw:
                try:
                    bday = date.fromisoformat(str(bday_raw)[:10])
                except ValueError:
                    bday = None
            osoby.append(OsobaAPI(imie=imie, nazwisko=nazwisko, plec=plec, data_urodzenia=bday))

        pozostalo -= len(rekordy)
        partia_nr += 1

    return osoby[:liczba]


def pobierz_osoby_randomuser(
    liczba: int,
    seed: int,
    timeout: int = 15,
) -> list[OsobaAPI]:
    """
    Pobiera dane osobowe z RandomUser API:
    https://randomuser.me/api/?results=...&seed=...&inc=name,gender,dob
    """
    osoby: list[OsobaAPI] = []
    pozostalo = liczba
    partia_nr = 0

    while pozostalo > 0:
        batch = min(pozostalo, 5000)
        params = urllib.parse.urlencode({
            "results": batch,
            "seed": f"zk-{seed}-{partia_nr}",
            "inc": "name,gender,dob",
        })
        url = f"https://randomuser.me/api/?{params}"
        payload = http_get_json(url, timeout=timeout)
        rekordy = payload.get("results", [])
        if not rekordy:
            raise RuntimeError("RandomUser API zwróciło pustą listę osób.")

        for item in rekordy:
            name_obj = item.get("name") or {}
            imie = str(name_obj.get("first", "")).strip()[:50]
            nazwisko = str(name_obj.get("last", "")).strip()[:50]
            if not imie or not nazwisko:
                continue
            plec = "K" if str(item.get("gender", "")).lower() == "female" else "M"
            bday: date | None = None
            dob_raw = (item.get("dob") or {}).get("date")
            if dob_raw:
                try:
                    bday = date.fromisoformat(str(dob_raw)[:10])
                except ValueError:
                    bday = None
            osoby.append(OsobaAPI(imie=imie, nazwisko=nazwisko, plec=plec, data_urodzenia=bday))

        pozostalo -= len(rekordy)
        partia_nr += 1

    return osoby[:liczba]


def pobierz_osoby_z_api(
    liczba: int,
    seed: int,
    zrodlo: str,
    timeout: int = 15,
) -> tuple[list[OsobaAPI], str]:
    """Pobiera osoby z wybranego API (z automatycznym przełączeniem na drugie API w razie awarii)."""
    kolejnosc = (
        [("fakerapi", pobierz_osoby_fakerapi), ("randomuser", pobierz_osoby_randomuser)]
        if zrodlo == "fakerapi"
        else [("randomuser", pobierz_osoby_randomuser), ("fakerapi", pobierz_osoby_fakerapi)]
    )

    bledy: list[str] = []
    for nazwa, funkcja in kolejnosc:
        try:
            print(f"[API] Pobieranie {liczba} osób z {nazwa}...")
            osoby = funkcja(liczba, seed, timeout=timeout)
            if len(osoby) >= liczba:
                print(f"[API] Pobrano {len(osoby)} osób z {nazwa}.")
                return osoby, nazwa
            bledy.append(f"{nazwa}: otrzymano za mało rekordów ({len(osoby)}/{liczba})")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            bledy.append(f"{nazwa}: {exc}")
            print(f"[API] Ostrzeżenie — nie udało się pobrać z {nazwa}: {exc}", file=sys.stderr)

    raise RuntimeError(
        "Nie udało się pobrać danych osobowych z żadnego zewnętrznego API:\n  - "
        + "\n  - ".join(bledy)
    )


def pobierz_sady_saos(max_stron: int = 2, timeout: int = 15) -> list[str]:
    """
    Pobiera prawdziwe polskie sądy powszechne z publicznego API SAOS:
    https://www.saos.org.pl/api/dump/commonCourts
    """
    print("[API] Pobieranie listy polskich sądów z SAOS API (saos.org.pl)...")
    sady: list[str] = []

    for page in range(max_stron):
        params = urllib.parse.urlencode({"pageSize": 100, "pageNumber": page})
        url = f"https://www.saos.org.pl/api/dump/commonCourts?{params}"
        payload = http_get_json(url, timeout=timeout)
        items = payload.get("items", [])
        if not items:
            break

        for court in items:
            name = str(court.get("name", "")).strip()
            # Kolumna wyroki.sad ma typ varchar(100)
            if name and len(name) <= 100:
                sady.append(name)

        links = payload.get("links") or []
        has_next = any(link.get("rel") == "next" for link in links)
        if not has_next:
            break

    # Usunięcie duplikatów z zachowaniem kolejności
    unikalne = list(dict.fromkeys(sady))
    if not unikalne:
        raise RuntimeError("SAOS API nie zwróciło żadnych sądów.")
    print(f"[API] Pobrano {len(unikalne)} sądów z SAOS API.")
    return unikalne


# ---------------------------------------------------------------------------
# Pomocnicze funkcje domenowe
# ---------------------------------------------------------------------------

def generuj_pesel(
    data_ur: date,
    plec: str,
    uzyte_pesele: set[str],
    rng: random.Random,
) -> str:
    """Generuje poprawny i unikalny 11-cyfrowy numer PESEL z cyfrą kontrolną."""
    rok = data_ur.year
    miesiac = data_ur.month
    dzien = data_ur.day

    if 1900 <= rok <= 1999:
        m_kod = miesiac
    elif 2000 <= rok <= 2099:
        m_kod = miesiac + 20
    elif 1800 <= rok <= 1899:
        m_kod = miesiac + 80
    else:
        m_kod = miesiac

    prefix = f"{rok % 100:02d}{m_kod:02d}{dzien:02d}"
    wagi = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)

    while True:
        seria = rng.randint(0, 999)
        cyfra_plci = rng.choice([1, 3, 5, 7, 9] if plec == "M" else [0, 2, 4, 6, 8])
        pierwsze_10 = f"{prefix}{seria:03d}{cyfra_plci}"
        suma = sum(int(c) * w for c, w in zip(pierwsze_10, wagi))
        kontrolna = (10 - (suma % 10)) % 10
        pesel = f"{pierwsze_10}{kontrolna}"
        if pesel not in uzyte_pesele:
            uzyte_pesele.add(pesel)
            return pesel


def losowy_timestamp(start: datetime, end: datetime, rng: random.Random) -> datetime:
    """Zwraca losowy timestamp w przedziale [start, end] z dokładnością do sekundy."""
    if end <= start:
        return start
    delta_sek = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, delta_sek))


# ---------------------------------------------------------------------------
# Struktury rekordów
# ---------------------------------------------------------------------------

@dataclass
class DaneBazy:
    cele: list[dict[str, Any]]
    personel: list[dict[str, Any]]
    wiezniowie: list[dict[str, Any]]
    wyroki: list[dict[str, Any]]
    przydzialy_cel: list[dict[str, Any]]
    widzenia: list[dict[str, Any]]
    incydenty: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Główna logika generowania
# ---------------------------------------------------------------------------

def generuj_dane(
    liczba_wiezniow: int,
    liczba_personelu: int,
    liczba_cel: int,
    seed: int,
    api_source: str,
    timeout: int,
) -> DaneBazy:
    rng = random.Random(seed)
    teraz = datetime.now().replace(microsecond=0) - timedelta(hours=1)
    dzis = teraz.date()

    # Pula osób do pobrania z API: więźniowie + personel + odwiedzający (zapas)
    liczba_odwiedzajacych_pula = max(50, liczba_wiezniow * 2)
    lacznie_osob = liczba_wiezniow + liczba_personelu + liczba_odwiedzajacych_pula

    osoby_api, _ = pobierz_osoby_z_api(
        liczba=lacznie_osob,
        seed=seed,
        zrodlo=api_source,
        timeout=timeout,
    )
    sady_api = pobierz_sady_saos(max_stron=2, timeout=timeout)

    osoby_personel = osoby_api[:liczba_personelu]
    osoby_wiezniowie = osoby_api[liczba_personelu:liczba_personelu + liczba_wiezniow]
    osoby_odwiedzajacy = osoby_api[liczba_personelu + liczba_wiezniow:]

    # 1. Generowanie cel
    cele: list[dict[str, Any]] = []
    liczniki_blokow: dict[str, int] = {b[0]: 0 for b in BLOKI_KONFIG}
    wagi_blokow = [0.22, 0.28, 0.28, 0.14, 0.08]

    for id_celi in range(1, liczba_cel + 1):
        blok, poziom, min_p, max_p = rng.choices(BLOKI_KONFIG, weights=wagi_blokow, k=1)[0]
        liczniki_blokow[blok] += 1
        pojemnosc = rng.randint(min_p, max_p)
        cele.append({
            "id_celi": id_celi,
            "blok": blok,
            "numer_celi": f"{liczniki_blokow[blok]:03d}",
            "pojemnosc": pojemnosc,
            "poziom_zabezpieczen": poziom,
        })

    laczna_pojemnosc = sum(c["pojemnosc"] for c in cele)
    wymagana_pojemnosc = int(liczba_wiezniow * 0.85) + 5
    while laczna_pojemnosc < wymagana_pojemnosc:
        id_celi = len(cele) + 1
        blok, poziom, min_p, max_p = rng.choice(BLOKI_KONFIG[:3])
        liczniki_blokow[blok] += 1
        pojemnosc = rng.randint(max(min_p, 4), max(max_p, 8))
        cele.append({
            "id_celi": id_celi,
            "blok": blok,
            "numer_celi": f"{liczniki_blokow[blok]:03d}",
            "pojemnosc": pojemnosc,
            "poziom_zabezpieczen": poziom,
        })
        laczna_pojemnosc += pojemnosc

    # 2. Generowanie personelu z danych API
    personel: list[dict[str, Any]] = []
    for id_funk, osoba in enumerate(osoby_personel, start=1):
        stopien = rng.choice(STOPNIE_SW) if rng.random() > 0.03 else None
        personel.append({
            "id_funkcjonariusza": id_funk,
            "numer_sluzbowy": f"SW-{2015 + (id_funk % 11)}-{id_funk:04d}",
            "imie": osoba.imie,
            "nazwisko": osoba.nazwisko,
            "stopien": stopien,
        })

    # 3. Generowanie więźniów, wyroków, przydziałów cel, widzeń i incydentów
    wiezniowie: list[dict[str, Any]] = []
    wyroki: list[dict[str, Any]] = []
    przydzialy_cel: list[dict[str, Any]] = []
    widzenia: list[dict[str, Any]] = []
    incydenty: list[dict[str, Any]] = []

    uzyte_pesele: set[str] = set()
    aktywne_oblozenie: dict[int, int] = {c["id_celi"]: 0 for c in cele}

    id_wyroku = 1
    id_przydzialu = 1
    id_widzenia = 1
    id_incydentu = 1

    max_data_ur = dzis - timedelta(days=18 * 365 + 5)
    min_data_ur = dzis - timedelta(days=80 * 365)

    for id_wieznia, osoba in enumerate(osoby_wiezniowie, start=1):
        dni_od_przyjecia = rng.randint(14, 6 * 365)
        data_przyjecia = teraz - timedelta(
            days=dni_od_przyjecia,
            hours=rng.randint(0, 10),
            minutes=rng.randint(0, 59),
        )

        # Używamy daty urodzenia z API, jeżeli spełnia wymóg wieku (>= 18 lat przy przyjęciu)
        max_ur_przy_przyjeciu = data_przyjecia.date() - timedelta(days=18 * 365 + 5)
        if (
            osoba.data_urodzenia is not None
            and min_data_ur <= osoba.data_urodzenia <= min(max_data_ur, max_ur_przy_przyjeciu)
        ):
            data_urodzenia = osoba.data_urodzenia
        else:
            wiek_przy_przyjeciu = rng.randint(18, 65)
            data_urodzenia = data_przyjecia.date() - timedelta(
                days=wiek_przy_przyjeciu * 365 + rng.randint(0, 364)
            )
            if data_urodzenia > max_data_ur:
                data_urodzenia = max_data_ur - timedelta(days=rng.randint(1, 365))

        pesel = (
            None
            if rng.random() < 0.05
            else generuj_pesel(data_urodzenia, osoba.plec, uzyte_pesele, rng)
        )

        status_docelowy = rng.choices(STATUSY_WIEZNIOW, weights=STATUSY_WAGI, k=1)[0]
        wolne_cele = [c for c in cele if aktywne_oblozenie[c["id_celi"]] < c["pojemnosc"]]
        if status_docelowy == "osadzony" and not wolne_cele:
            status_docelowy = "zwolniony"

        numer_ewidencyjny = f"ZK/{data_przyjecia.year}/{id_wieznia:05d}"

        wiezniowie.append({
            "id_wieznia": id_wieznia,
            "numer_ewidencyjny": numer_ewidencyjny,
            "pesel": pesel,
            "imie": osoba.imie,
            "nazwisko": osoba.nazwisko,
            "data_urodzenia": data_urodzenia,
            "data_przyjecia": data_przyjecia,
            "status": status_docelowy,
        })

        if status_docelowy == "osadzony":
            koniec_pobytu = teraz
        else:
            max_dni_pobytu = max(2, int((teraz - data_przyjecia).total_seconds() // 86400) - 1)
            dlugosc_pobytu_dni = rng.randint(1, max_dni_pobytu)
            koniec_pobytu = data_przyjecia + timedelta(
                days=dlugosc_pobytu_dni,
                hours=rng.randint(1, 8),
                minutes=rng.randint(0, 59),
            )
            if koniec_pobytu > teraz:
                koniec_pobytu = teraz - timedelta(minutes=rng.randint(10, 120))

        # --- WYROKI ---
        liczba_wyrokow = rng.choices([1, 2, 3], weights=[0.65, 0.25, 0.10], k=1)[0]
        for idx_w in range(liczba_wyrokow):
            artykul, min_dni, max_dni = rng.choice(ARTYKULY_KK)
            if idx_w == 0:
                data_rozp = data_przyjecia.date()
            else:
                przesuniecie = rng.randint(0, max(1, (koniec_pobytu.date() - data_przyjecia.date()).days))
                data_rozp = data_przyjecia.date() + timedelta(days=przesuniecie)

            planowana_koniec = data_rozp + timedelta(days=rng.randint(min_dni, max_dni))

            if status_docelowy == "osadzony":
                if idx_w == 0 and planowana_koniec <= dzis:
                    planowana_koniec = dzis + timedelta(days=rng.randint(30, 1825))
                rzeczywista_koniec = None if (idx_w == 0 or planowana_koniec > dzis) else planowana_koniec
            elif status_docelowy == "zwolniony":
                rzeczywista_koniec = max(data_rozp, koniec_pobytu.date())
                if planowana_koniec < rzeczywista_koniec:
                    planowana_koniec = rzeczywista_koniec + timedelta(days=rng.randint(0, 180))
            else:
                rzeczywista_koniec = max(data_rozp, koniec_pobytu.date()) if status_docelowy == "zmarly" else None

            rok_akt = max(2015, data_rozp.year - rng.randint(0, 2))
            wydzial = rng.choice(["II K", "III K", "IV K", "V K", "VIII K", "XII K"])
            sygnatura = f"{wydzial} {rng.randint(10, 1999)}/{rok_akt % 100:02d}"

            wyroki.append({
                "id_wyroku": id_wyroku,
                "id_wieznia": id_wieznia,
                "sygnatura_akt": sygnatura,
                "sad": rng.choice(sady_api),
                "artykul_kk": artykul,
                "data_rozpoczecia": data_rozp,
                "planowana_data_zakonczenia": planowana_koniec,
                "rzeczywista_data_zakonczenia": rzeczywista_koniec,
            })
            id_wyroku += 1

        # --- PRZYDZIAŁY CEL ---
        liczba_przydzialow = rng.choices([1, 2, 3, 4], weights=[0.45, 0.30, 0.17, 0.08], k=1)[0]
        czas_pobytu_sek = int((koniec_pobytu - data_przyjecia).total_seconds())
        if czas_pobytu_sek < liczba_przydzialow * 3600:
            liczba_przydzialow = 1

        punkty_czasu = [data_przyjecia]
        if liczba_przydzialow > 1:
            podzialy = sorted(
                rng.sample(range(3600, max(3601, czas_pobytu_sek - 3600)), liczba_przydzialow - 1)
            )
            for sek in podzialy:
                punkty_czasu.append(data_przyjecia + timedelta(seconds=sek))
        punkty_czasu.append(koniec_pobytu)

        poprzednia_cela: int | None = None
        for idx_p in range(liczba_przydzialow):
            jest_ostatni = idx_p == liczba_przydzialow - 1
            data_od = punkty_czasu[idx_p]

            if jest_ostatni and status_docelowy == "osadzony":
                kandydaci = [
                    c for c in cele
                    if aktywne_oblozenie[c["id_celi"]] < c["pojemnosc"]
                    and c["id_celi"] != poprzednia_cela
                ]
                if not kandydaci:
                    kandydaci = [
                        c for c in cele
                        if aktywne_oblozenie[c["id_celi"]] < c["pojemnosc"]
                    ]
                cela = rng.choice(kandydaci)
                aktywne_oblozenie[cela["id_celi"]] += 1
                data_do = None
            else:
                kandydaci = [c for c in cele if c["id_celi"] != poprzednia_cela] or cele
                cela = rng.choice(kandydaci)
                data_do = punkty_czasu[idx_p + 1]
                if data_do <= data_od:
                    data_do = data_od + timedelta(hours=1)

            poprzednia_cela = cela["id_celi"]
            przydzialy_cel.append({
                "id_przydzialu": id_przydzialu,
                "id_wieznia": id_wieznia,
                "id_celi": cela["id_celi"],
                "data_od": data_od,
                "data_do": data_do,
            })
            id_przydzialu += 1

        # --- WIDZENIA ---
        liczba_widzen = rng.choices([0, 1, 2, 3, 4, 5, 6], weights=[0.18, 0.22, 0.22, 0.16, 0.10, 0.07, 0.05], k=1)[0]
        for _ in range(liczba_widzen):
            odw = rng.choice(osoby_odwiedzajacy)
            relacja = rng.choice(RELACJE_ODWIEDZAJACYCH)

            data_widz = losowy_timestamp(data_przyjecia, koniec_pobytu, rng)
            data_widz = data_widz.replace(
                hour=rng.randint(8, 15),
                minute=rng.choice([0, 15, 30, 45]),
                second=0,
            )
            if data_widz < data_przyjecia:
                data_widz = data_przyjecia + timedelta(hours=1)
            if data_widz > koniec_pobytu:
                data_widz = koniec_pobytu - timedelta(minutes=30)

            widzenia.append({
                "id_widzenia": id_widzenia,
                "id_wieznia": id_wieznia,
                "imie_odwiedzajacego": odw.imie,
                "nazwisko_odwiedzajacego": odw.nazwisko,
                "relacja": relacja if rng.random() > 0.03 else None,
                "data_widzenia": data_widz,
                "czas_trwania_min": rng.choice([30, 45, 60, 60, 90, 120, 180]),
            })
            id_widzenia += 1

        # --- INCYDENTY ---
        liczba_incydentow = rng.choices([0, 1, 2, 3, 4], weights=[0.42, 0.30, 0.16, 0.08, 0.04], k=1)[0]
        for _ in range(liczba_incydentow):
            typ = rng.choices(
                ["bojka", "kontrabanda", "proba_ucieczki", "nagroda", "inne"],
                weights=[0.24, 0.22, 0.06, 0.28, 0.20],
                k=1,
            )[0]
            incydenty.append({
                "id_incydentu": id_incydentu,
                "id_wieznia": id_wieznia,
                "id_funkcjonariusza": rng.randint(1, liczba_personelu) if rng.random() > 0.03 else None,
                "data_zdarzenia": losowy_timestamp(data_przyjecia, koniec_pobytu, rng),
                "typ": typ,
                "opis": rng.choice(OPISY_INCYDENTOW[typ]),
            })
            id_incydentu += 1

    dane = DaneBazy(
        cele=cele,
        personel=personel,
        wiezniowie=wiezniowie,
        wyroki=wyroki,
        przydzialy_cel=przydzialy_cel,
        widzenia=widzenia,
        incydenty=incydenty,
    )
    waliduj_dane(dane)
    return dane


# ---------------------------------------------------------------------------
# Walidacja spójności wygenerowanych danych
# ---------------------------------------------------------------------------

def waliduj_dane(dane: DaneBazy) -> None:
    """Weryfikuje wszystkie reguły integralności z dokumentu projektowego."""
    dzis = date.today()
    limit_wieku = dzis - timedelta(days=17 * 365 + 4)

    pary_cel: set[tuple[str, str]] = set()
    pojemnosci: dict[int, int] = {}
    for c in dane.cele:
        klucz = (c["blok"], c["numer_celi"])
        assert klucz not in pary_cel, f"Duplikat celi: {klucz}"
        pary_cel.add(klucz)
        assert 0 < c["pojemnosc"] <= 20
        assert c["poziom_zabezpieczen"] in {"otwarty", "polotwarty", "zamkniety", "izolatka"}
        pojemnosci[c["id_celi"]] = c["pojemnosc"]

    numery_sluzb = {p["numer_sluzbowy"] for p in dane.personel}
    assert len(numery_sluzb) == len(dane.personel)

    pesele: set[str] = set()
    nr_ewid: set[str] = set()
    statusy_w: dict[int, str] = {}
    for w in dane.wiezniowie:
        assert w["numer_ewidencyjny"] not in nr_ewid
        nr_ewid.add(w["numer_ewidencyjny"])
        assert 1 <= len(w["imie"]) <= 50 and 1 <= len(w["nazwisko"]) <= 50
        if w["pesel"] is not None:
            assert len(w["pesel"]) == 11 and w["pesel"].isdigit()
            assert w["pesel"] not in pesele
            pesele.add(w["pesel"])
        assert w["data_urodzenia"] <= limit_wieku
        assert w["status"] in {"osadzony", "zwolniony", "przeniesiony", "zbiegly", "zmarly"}
        statusy_w[w["id_wieznia"]] = w["status"]

    for wyr in dane.wyroki:
        assert 1 <= len(wyr["sad"]) <= 100
        assert wyr["planowana_data_zakonczenia"] >= wyr["data_rozpoczecia"]
        if wyr["rzeczywista_data_zakonczenia"] is not None:
            assert wyr["rzeczywista_data_zakonczenia"] >= wyr["data_rozpoczecia"]

    aktywne_na_wieznia: set[int] = set()
    oblozenie_celi: dict[int, int] = {}
    for p in dane.przydzialy_cel:
        if p["data_do"] is None:
            assert p["id_wieznia"] not in aktywne_na_wieznia, "Więzień ma >1 aktywny przydział!"
            assert statusy_w[p["id_wieznia"]] == "osadzony", "Nieaktywny więzień ma otwarty przydział!"
            aktywne_na_wieznia.add(p["id_wieznia"])
            oblozenie_celi[p["id_celi"]] = oblozenie_celi.get(p["id_celi"], 0) + 1
            assert oblozenie_celi[p["id_celi"]] <= pojemnosci[p["id_celi"]], "Przekroczono pojemność celi!"
        else:
            assert p["data_do"] > p["data_od"], "data_do <= data_od!"

    for wid in dane.widzenia:
        assert 1 <= wid["czas_trwania_min"] <= 240

    for inc in dane.incydenty:
        assert inc["typ"] in {"bojka", "kontrabanda", "proba_ucieczki", "nagroda", "inne"}
        assert len(inc["opis"].strip()) >= 5


# ---------------------------------------------------------------------------
# Eksport do SQL (PostgreSQL) oraz CSV
# ---------------------------------------------------------------------------

def sql_val(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(val, date):
        return f"'{val.strftime('%Y-%m-%d')}'"
    escaped = str(val).replace("'", "''")
    return f"'{escaped}'"


def zapisz_insert_batch(
    f,
    tabela: str,
    kolumny: list[str],
    wiersze: list[dict[str, Any]],
    batch_size: int = 200,
) -> None:
    if not wiersze:
        return
    cols_sql = ", ".join(kolumny)
    for i in range(0, len(wiersze), batch_size):
        paczkowane = wiersze[i:i + batch_size]
        f.write(f"INSERT INTO {tabela} ({cols_sql}) VALUES\n")
        linie = []
        for row in paczkowane:
            vals = ", ".join(sql_val(row[k]) for k in kolumny)
            linie.append(f"    ({vals})")
        f.write(",\n".join(linie))
        f.write(";\n\n")


def eksportuj_sql(dane: DaneBazy, sciezka: Path) -> None:
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    with sciezka.open("w", encoding="utf-8") as f:
        f.write("-- =====================================================================\n")
        f.write("-- Dane testowe: System Ewidencji Zakładu Karnego (PostgreSQL)\n")
        f.write("-- Źródła zewnętrzne: FakerAPI / RandomUser + SAOS API (saos.org.pl)\n")
        f.write(f"-- Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("-- =====================================================================\n\n")
        f.write("BEGIN;\n\n")

        f.write("-- 1. Cele\n")
        zapisz_insert_batch(
            f,
            "cele",
            ["id_celi", "blok", "numer_celi", "pojemnosc", "poziom_zabezpieczen"],
            dane.cele,
        )

        f.write("-- 2. Personel\n")
        zapisz_insert_batch(
            f,
            "personel",
            ["id_funkcjonariusza", "numer_sluzbowy", "imie", "nazwisko", "stopien"],
            dane.personel,
        )

        f.write("-- 3. Więźniowie (początkowo status 'osadzony' dla zgodności z wyzwalaczami)\n")
        wiezniowie_start = [{**w, "status": "osadzony"} for w in dane.wiezniowie]
        zapisz_insert_batch(
            f,
            "wiezniowie",
            [
                "id_wieznia", "numer_ewidencyjny", "pesel", "imie",
                "nazwisko", "data_urodzenia", "data_przyjecia", "status",
            ],
            wiezniowie_start,
        )

        f.write("-- 4. Wyroki\n")
        zapisz_insert_batch(
            f,
            "wyroki",
            [
                "id_wyroku", "id_wieznia", "sygnatura_akt", "sad", "artykul_kk",
                "data_rozpoczecia", "planowana_data_zakonczenia", "rzeczywista_data_zakonczenia",
            ],
            dane.wyroki,
        )

        f.write("-- 5. Przydziały cel\n")
        zapisz_insert_batch(
            f,
            "przydzialy_cel",
            ["id_przydzialu", "id_wieznia", "id_celi", "data_od", "data_do"],
            dane.przydzialy_cel,
        )

        f.write("-- 6. Widzenia\n")
        zapisz_insert_batch(
            f,
            "widzenia",
            [
                "id_widzenia", "id_wieznia", "imie_odwiedzajacego",
                "nazwisko_odwiedzajacego", "relacja", "data_widzenia", "czas_trwania_min",
            ],
            dane.widzenia,
        )

        f.write("-- 7. Incydenty\n")
        zapisz_insert_batch(
            f,
            "incydenty",
            ["id_incydentu", "id_wieznia", "id_funkcjonariusza", "data_zdarzenia", "typ", "opis"],
            dane.incydenty,
        )

        nieaktywni = [w for w in dane.wiezniowie if w["status"] != "osadzony"]
        if nieaktywni:
            f.write("-- 8. Aktualizacja statusów więźniów nieaktywnych\n")
            pogrupowane: dict[str, list[int]] = {}
            for w in nieaktywni:
                pogrupowane.setdefault(w["status"], []).append(w["id_wieznia"])
            for status, ids in sorted(pogrupowane.items()):
                ids_str = ", ".join(str(i) for i in ids)
                f.write(
                    f"UPDATE wiezniowie SET status = {sql_val(status)} "
                    f"WHERE id_wieznia IN ({ids_str});\n"
                )
            f.write("\n")

        f.write("-- 9. Synchronizacja sekwencji (jeśli tabele używają SERIAL / IDENTITY)\n")
        f.write(
            "DO $$\n"
            "DECLARE\n"
            "    rec RECORD;\n"
            "    seq_name TEXT;\n"
            "    max_id BIGINT;\n"
            "BEGIN\n"
            "    FOR rec IN\n"
            "        SELECT * FROM (VALUES\n"
            "            ('cele', 'id_celi'),\n"
            "            ('personel', 'id_funkcjonariusza'),\n"
            "            ('wiezniowie', 'id_wieznia'),\n"
            "            ('wyroki', 'id_wyroku'),\n"
            "            ('przydzialy_cel', 'id_przydzialu'),\n"
            "            ('widzenia', 'id_widzenia'),\n"
            "            ('incydenty', 'id_incydentu')\n"
            "        ) AS t(tbl, col)\n"
            "    LOOP\n"
            "        seq_name := pg_get_serial_sequence(rec.tbl, rec.col);\n"
            "        IF seq_name IS NOT NULL THEN\n"
            "            EXECUTE format('SELECT COALESCE(MAX(%I), 1) FROM %I', rec.col, rec.tbl)\n"
            "                INTO max_id;\n"
            "            PERFORM setval(seq_name, max_id, true);\n"
            "        END IF;\n"
            "    END LOOP;\n"
            "END $$;\n\n"
        )

        f.write("COMMIT;\n")


def eksportuj_csv(dane: DaneBazy, katalog: Path) -> None:
    katalog.mkdir(parents=True, exist_ok=True)
    tabele: list[tuple[str, list[dict[str, Any]]]] = [
        ("cele", dane.cele),
        ("personel", dane.personel),
        ("wiezniowie", dane.wiezniowie),
        ("wyroki", dane.wyroki),
        ("przydzialy_cel", dane.przydzialy_cel),
        ("widzenia", dane.widzenia),
        ("incydenty", dane.incydenty),
    ]
    for nazwa, wiersze in tabele:
        if not wiersze:
            continue
        sciezka = katalog / f"{nazwa}.csv"
        kolumny = list(wiersze[0].keys())
        with sciezka.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=kolumny)
            writer.writeheader()
            for row in wiersze:
                formatted = {}
                for k, v in row.items():
                    if isinstance(v, datetime):
                        formatted[k] = v.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(v, date):
                        formatted[k] = v.strftime("%Y-%m-%d")
                    elif v is None:
                        formatted[k] = ""
                    else:
                        formatted[k] = v
                writer.writerow(formatted)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generator danych testowych dla bazy danych Zakładu Karnego (z zewnętrznych API)."
    )
    parser.add_argument(
        "--wiezniowie", type=int, default=100,
        help="Liczba więźniów do wygenerowania (domyślnie: 100)",
    )
    parser.add_argument(
        "--personel", type=int, default=30,
        help="Liczba funkcjonariuszy do wygenerowania (domyślnie: 30)",
    )
    parser.add_argument(
        "--cele", type=int, default=40,
        help="Minimalna liczba cel do wygenerowania (domyślnie: 40)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Ziarno generatora losowego (domyślnie: 42)",
    )
    parser.add_argument(
        "--api-source", choices=["fakerapi", "randomuser"], default="fakerapi",
        help="Główne źródło API dla danych osobowych (domyślnie: fakerapi)",
    )
    parser.add_argument(
        "--timeout", type=int, default=15,
        help="Limit czasu na zapytanie HTTP w sekundach (domyślnie: 15)",
    )
    parser.add_argument(
        "--format", choices=["sql", "csv"], default="sql",
        help="Format wyjściowy: sql lub csv (domyślnie: sql)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Ścieżka pliku SQL lub katalogu CSV (domyślnie: seed_data.sql lub ./csv_data)",
    )
    args = parser.parse_args()

    dane = generuj_dane(
        liczba_wiezniow=args.wiezniowie,
        liczba_personelu=args.personel,
        liczba_cel=args.cele,
        seed=args.seed,
        api_source=args.api_source,
        timeout=args.timeout,
    )

    if args.format == "sql":
        sciezka = Path(args.output or "seed_data.sql")
        eksportuj_sql(dane, sciezka)
        cel_wyjscia = str(sciezka.resolve())
    else:
        katalog = Path(args.output or "csv_data")
        eksportuj_csv(dane, katalog)
        cel_wyjscia = str(katalog.resolve())

    aktywni = sum(1 for w in dane.wiezniowie if w["status"] == "osadzony")
    print("Wygenerowano dane poprawnie:")
    print(f"  - cele:           {len(dane.cele)}")
    print(f"  - personel:       {len(dane.personel)}")
    print(f"  - wiezniowie:     {len(dane.wiezniowie)} (w tym aktywni osadzeni: {aktywni})")
    print(f"  - wyroki:         {len(dane.wyroki)}")
    print(f"  - przydzialy_cel: {len(dane.przydzialy_cel)}")
    print(f"  - widzenia:       {len(dane.widzenia)}")
    print(f"  - incydenty:      {len(dane.incydenty)}")
    print(f"Zapisano do: {cel_wyjscia}")


if __name__ == "__main__":
    main()
