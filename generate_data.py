#!/usr/bin/env python3
"""
Generator danych testowych dla bazy danych Systemu Ewidencji Zakładu Karnego (PostgreSQL).

Źródła danych:
- Dane osobowe (imiona, nazwiska, płeć, daty urodzenia):
    FakerAPI v2 (https://fakerapi.it/api/v2/persons?_locale=pl_PL) — bez fallbacku.
- Sądy powszechne oraz słowniki domenowe (stopnie SW, artykuły KK, incydenty, bloki cel):
    wbudowane słowniki domenowe.

Wyjście:
- Wyłącznie skrypt SQL dla PostgreSQL (transakcja BEGIN..COMMIT + synchronizacja sekwencji).

Zgodny ze schematem, ograniczeniami integralności i wyzwalaczami z Bazy-danych-projekt-1.pdf.
Brak zewnętrznych zależności (tylko biblioteka standardowa Pythona).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Słowniki domenowe (sądy oraz wartości charakterystyczne dla zakładu karnego)
# ---------------------------------------------------------------------------

SADY = [
    "Sąd Rejonowy dla m.st. Warszawy w Warszawie",
    "Sąd Okręgowy w Warszawie",
    "Sąd Apelacyjny w Warszawie",
    "Sąd Rejonowy dla Krakowa-Śródmieścia w Krakowie",
    "Sąd Okręgowy w Krakowie",
    "Sąd Apelacyjny w Krakowie",
    "Sąd Rejonowy Gdańsk-Południe w Gdańsku",
    "Sąd Okręgowy w Gdańsku",
    "Sąd Apelacyjny w Gdańsku",
    "Sąd Rejonowy dla Wrocławia-Śródmieścia we Wrocławiu",
    "Sąd Okręgowy we Wrocławiu",
    "Sąd Apelacyjny we Wrocławiu",
    "Sąd Rejonowy Poznań-Stare Miasto w Poznaniu",
    "Sąd Okręgowy w Poznaniu",
    "Sąd Apelacyjny w Poznaniu",
    "Sąd Rejonowy dla Łodzi-Śródmieścia w Łodzi",
    "Sąd Okręgowy w Łodzi",
    "Sąd Apelacyjny w Łodzi",
    "Sąd Rejonowy Katowice-Wschód w Katowicach",
    "Sąd Okręgowy w Katowicach",
    "Sąd Apelacyjny w Katowicach",
    "Sąd Rejonowy Lublin-Zachód w Lublinie",
    "Sąd Okręgowy w Lublinie",
    "Sąd Rejonowy Szczecin-Centrum w Szczecinie",
    "Sąd Okręgowy w Szczecinie",
    "Sąd Rejonowy w Bydgoszczy",
    "Sąd Okręgowy w Bydgoszczy",
    "Sąd Rejonowy w Białymstoku",
    "Sąd Okręgowy w Białymstoku",
    "Sąd Rejonowy w Rzeszowie",
    "Sąd Okręgowy w Rzeszowie",
    "Sąd Rejonowy w Toruniu",
    "Sąd Rejonowy w Olsztynie",
    "Sąd Rejonowy w Kielcach",
    "Sąd Rejonowy w Opolu",
    "Sąd Rejonowy w Zielonej Górze",
]

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

STATUSY_WIEZNIOW = ("osadzony", "zwolniony", "przeniesiony", "zbiegly", "zmarly")
STATUSY_WAGI = [0.68, 0.18, 0.08, 0.03, 0.03]
POZIOMY_ZABEZPIECZEN = ("otwarty", "polotwarty", "zamkniety", "izolatka")
TYPY_INCYDENTOW = ("bojka", "kontrabanda", "proba_ucieczki", "nagroda", "inne")

IMIONA_MESKIE_NA_A = {"Kuba", "Barnaba", "Bonawentura", "Kosma", "Jarema", "Dyzma"}
PESEL_RE = re.compile(r"^[0-9]{11}$")
PESEL_WAGI = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


# ---------------------------------------------------------------------------
# Wyjątek walidacji
# ---------------------------------------------------------------------------

class ValidationError(ValueError):
    """Błąd naruszenia reguł integralności danych przed eksportem do SQL."""

    def __init__(self, bledy: list[str]) -> None:
        self.bledy = bledy
        naglowek = f"Wykryto {len(bledy)} błędów walidacji danych:"
        szczegoly = "\n".join(f"  - {b}" for b in bledy[:50])
        if len(bledy) > 50:
            szczegoly += f"\n  ... oraz {len(bledy) - 50} kolejnych błędów."
        super().__init__(f"{naglowek}\n{szczegoly}")


# ---------------------------------------------------------------------------
# Klient FakerAPI v2 (bez fallbacku)
# ---------------------------------------------------------------------------

@dataclass
class OsobaAPI:
    imie: str
    nazwisko: str
    plec: str  # "M" lub "K"
    data_urodzenia: date | None


def ustal_plec_po_imieniu(imie: str, domyslna: str) -> str:
    """Koryguje płeć na podstawie polskiego imienia (FakerAPI bywa niespójne z polem gender)."""
    if not imie:
        return domyslna
    if imie in IMIONA_MESKIE_NA_A:
        return "M"
    if imie.endswith("a"):
        return "K"
    return "M"


def dopasuj_nazwisko_do_plci(nazwisko: str, plec: str) -> str:
    """Dopasowuje końcówki polskich nazwisk (-ski/-ska, -cki/-cka, -dzki/-dzka) do płci."""
    if plec == "K" and nazwisko.endswith(("ski", "cki", "dzki")):
        return nazwisko[:-1] + "a"
    if plec == "M" and nazwisko.endswith(("ska", "cka", "dzka")):
        return nazwisko[:-1] + "i"
    return nazwisko


def http_get_json(url: str, timeout: int = 15) -> Any:
    """Wykonuje żądanie HTTP GET i parsuje odpowiedź JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ZakladKarnyDataGenerator/2.0 (Python urllib)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def pobierz_osoby_fakerapi(
    liczba: int,
    seed: int,
    timeout: int = 15,
) -> list[OsobaAPI]:
    """
    Pobiera polskie dane osobowe z FakerAPI v2 (bez fallbacku):
    https://fakerapi.it/api/v2/persons?_locale=pl_PL&_quantity=...&_seed=...
    """
    print(f"[API] Pobieranie {liczba} osób z FakerAPI (pl_PL)...")
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
            plec_api = "K" if str(item.get("gender", "male")).lower() == "female" else "M"
            plec = ustal_plec_po_imieniu(imie, plec_api)
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

    if len(osoby) < liczba:
        raise RuntimeError(f"FakerAPI zwróciło za mało poprawnych osób ({len(osoby)}/{liczba}).")

    print(f"[API] Pobrano {len(osoby[:liczba])} osób z FakerAPI.")
    return osoby[:liczba]


# ---------------------------------------------------------------------------
# Pomocnicze funkcje domenowe (PESEL, znaczniki czasu)
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

    while True:
        seria = rng.randint(0, 999)
        cyfra_plci = rng.choice([1, 3, 5, 7, 9] if plec == "M" else [0, 2, 4, 6, 8])
        pierwsze_10 = f"{prefix}{seria:03d}{cyfra_plci}"
        suma = sum(int(c) * w for c, w in zip(pierwsze_10, PESEL_WAGI))
        kontrolna = (10 - (suma % 10)) % 10
        pesel = f"{pierwsze_10}{kontrolna}"
        if pesel not in uzyte_pesele:
            uzyte_pesele.add(pesel)
            return pesel


def weryfikuj_pesel(pesel: str, data_ur: date) -> str | None:
    """
    Weryfikuje poprawność numeru PESEL:
    - format dokładnie 11 cyfr (CHECK z bazy),
    - poprawna cyfra kontrolna,
    - zakodowana data zgodna z data_urodzenia.
    Zwraca opis błędu albo None, jeśli PESEL jest poprawny.
    """
    if not PESEL_RE.match(pesel):
        return f"PESEL '{pesel}' nie spełnia formatu ^[0-9]{{11}}$"

    suma = sum(int(c) * w for c, w in zip(pesel[:10], PESEL_WAGI))
    oczekiwana_kontrolna = (10 - (suma % 10)) % 10
    if int(pesel[10]) != oczekiwana_kontrolna:
        return f"PESEL '{pesel}' ma błędną cyfrę kontrolną (oczekiwano {oczekiwana_kontrolna})"

    yy = int(pesel[0:2])
    mm = int(pesel[2:4])
    dd = int(pesel[4:6])

    if 1 <= mm <= 12:
        rok, miesiac = 1900 + yy, mm
    elif 21 <= mm <= 32:
        rok, miesiac = 2000 + yy, mm - 20
    elif 81 <= mm <= 92:
        rok, miesiac = 1800 + yy, mm - 80
    else:
        return f"PESEL '{pesel}' ma niepoprawny kod miesiąca ({mm})"

    try:
        data_z_pesel = date(rok, miesiac, dd)
    except ValueError:
        return f"PESEL '{pesel}' koduje nieistniejącą datę ({rok}-{miesiac:02d}-{dd:02d})"

    if data_z_pesel != data_ur:
        return f"PESEL '{pesel}' koduje datę {data_z_pesel}, różną od data_urodzenia={data_ur}"

    return None


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
    timeout: int,
) -> DaneBazy:
    rng = random.Random(seed)
    teraz = datetime.now().replace(microsecond=0) - timedelta(hours=1)
    dzis = teraz.date()

    # Pula osób z FakerAPI: personel + więźniowie + odwiedzający
    liczba_odwiedzajacych_pula = max(50, liczba_wiezniow * 2)
    lacznie_osob = liczba_personelu + liczba_wiezniow + liczba_odwiedzajacych_pula
    osoby_api = pobierz_osoby_fakerapi(liczba=lacznie_osob, seed=seed, timeout=timeout)

    osoby_personel = osoby_api[:liczba_personelu]
    osoby_wiezniowie = osoby_api[liczba_personelu:liczba_personelu + liczba_wiezniow]
    osoby_odwiedzajacy = osoby_api[liczba_personelu + liczba_wiezniow:]

    # 1. Cele
    cele: list[dict[str, Any]] = []
    liczniki_blokow: dict[str, int] = {b[0]: 0 for b in BLOKI_KONFIG}
    wagi_blokow = [0.22, 0.28, 0.28, 0.14, 0.08]

    for id_celi in range(1, liczba_cel + 1):
        blok, poziom, min_p, max_p = rng.choices(BLOKI_KONFIG, weights=wagi_blokow, k=1)[0]
        liczniki_blokow[blok] += 1
        cele.append({
            "id_celi": id_celi,
            "blok": blok,
            "numer_celi": f"{liczniki_blokow[blok]:03d}",
            "pojemnosc": rng.randint(min_p, max_p),
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

    # 2. Personel
    personel: list[dict[str, Any]] = []
    for id_funk, osoba in enumerate(osoby_personel, start=1):
        personel.append({
            "id_funkcjonariusza": id_funk,
            "numer_sluzbowy": f"SW-{2015 + (id_funk % 11)}-{id_funk:04d}",
            "imie": osoba.imie,
            "nazwisko": osoba.nazwisko,
            "stopien": rng.choice(STOPNIE_SW) if rng.random() > 0.03 else None,
        })

    # 3. Więźniowie, wyroki, przydziały cel, widzenia, incydenty
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

        pesel = generuj_pesel(data_urodzenia, osoba.plec, uzyte_pesele, rng)

        status_docelowy = rng.choices(STATUSY_WIEZNIOW, weights=STATUSY_WAGI, k=1)[0]
        wolne_cele = [c for c in cele if aktywne_oblozenie[c["id_celi"]] < c["pojemnosc"]]
        if status_docelowy == "osadzony" and not wolne_cele:
            status_docelowy = "zwolniony"

        wiezniowie.append({
            "id_wieznia": id_wieznia,
            "numer_ewidencyjny": f"ZK/{data_przyjecia.year}/{id_wieznia:05d}",
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

        # --- WYROKI (sądy ze słownika SADY) ---
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

            wyroki.append({
                "id_wyroku": id_wyroku,
                "id_wieznia": id_wieznia,
                "sygnatura_akt": f"{wydzial} {rng.randint(10, 1999)}/{rok_akt % 100:02d}",
                "sad": rng.choice(SADY),
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
                ] or [
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
                data_widz = data_przyjecia + timedelta(minutes=30)
            if data_widz > koniec_pobytu:
                data_widz = koniec_pobytu - timedelta(minutes=30)
            if data_widz < data_przyjecia:
                data_widz = data_przyjecia

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
                TYPY_INCYDENTOW,
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
# Rozbudowana walidacja danych (bez assert, zbiera wszystkie naruszenia)
# ---------------------------------------------------------------------------

def _sprawdz_tekst(
    bledy: list[str],
    kontekst: str,
    wartosc: Any,
    max_dlugosc: int,
    wymagany: bool = True,
    min_dlugosc: int = 1,
) -> None:
    if wartosc is None:
        if wymagany:
            bledy.append(f"{kontekst}: wartość wymagana (NOT NULL), otrzymano NULL")
        return
    if not isinstance(wartosc, str):
        bledy.append(f"{kontekst}: oczekiwano typu str, otrzymano {type(wartosc).__name__}")
        return
    oczyszczony = wartosc.strip()
    if len(oczyszczony) < min_dlugosc:
        bledy.append(f"{kontekst}: zbyt krótki tekst (min {min_dlugosc}, otrzymano {len(oczyszczony)})")
    if len(wartosc) > max_dlugosc:
        bledy.append(f"{kontekst}: przekroczono limit długości ({len(wartosc)} > {max_dlugosc})")


def waliduj_dane(dane: DaneBazy) -> None:
    """
    Kompleksowa walidacja wszystkich tabel przed eksportem do PostgreSQL:
    - typy, NOT NULL, limity długości kolumn (varchar/char),
    - unikalność PK i kolumn UNIQUE (w tym par i indeksów częściowych),
    - integralność wszystkich kluczy obcych (FK),
    - wszystkie reguły CHECK z Bazy-danych-projekt-1.pdf (m.in. PESEL z sumą kontrolną
      i zgodnością z datą urodzenia, wiek >= 17 lat, daty wyroków, czas widzeń, opisy),
    - spójność czasowa (brak nakładających się przydziałów cel, brak dat zdarzeń
      przed przyjęciem lub w przyszłości),
    - zgodność z wyzwalaczami (pojemność cel, jeden aktywny przydział dla osadzonego,
      brak aktywnych przydziałów dla osób o statusie innym niż 'osadzony').
    """
    bledy: list[str] = []
    teraz = datetime.now()
    dzis = teraz.date()
    limit_wieku_17 = dzis - timedelta(days=17 * 365 + 4)

    # --- 1. CELE ---
    cele_ids: set[int] = set()
    pary_cel: set[tuple[str, str]] = set()
    pojemnosci_cel: dict[int, int] = {}

    for c in dane.cele:
        cid = c["id_celi"]
        ctx = f"cele(id_celi={cid})"
        if not isinstance(cid, int) or cid <= 0 or cid in cele_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_celi")
        cele_ids.add(cid)

        _sprawdz_tekst(bledy, f"{ctx}.blok", c["blok"], max_dlugosc=10)
        _sprawdz_tekst(bledy, f"{ctx}.numer_celi", c["numer_celi"], max_dlugosc=10)

        klucz = (c["blok"], c["numer_celi"])
        if klucz in pary_cel:
            bledy.append(f"{ctx}: naruszenie UNIQUE(blok, numer_celi) dla {klucz}")
        pary_cel.add(klucz)

        poj = c["pojemnosc"]
        if not isinstance(poj, int) or not (0 < poj <= 20):
            bledy.append(f"{ctx}.pojemnosc: wartość {poj} poza zakresem (1..20)")
        pojemnosci_cel[cid] = poj

        if c["poziom_zabezpieczen"] not in POZIOMY_ZABEZPIECZEN:
            bledy.append(f"{ctx}.poziom_zabezpieczen: niedozwolona wartość '{c['poziom_zabezpieczen']}'")

    # --- 2. PERSONEL ---
    personel_ids: set[int] = set()
    numery_sluzbowe: set[str] = set()

    for p in dane.personel:
        pid = p["id_funkcjonariusza"]
        ctx = f"personel(id_funkcjonariusza={pid})"
        if not isinstance(pid, int) or pid <= 0 or pid in personel_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_funkcjonariusza")
        personel_ids.add(pid)

        _sprawdz_tekst(bledy, f"{ctx}.numer_sluzbowy", p["numer_sluzbowy"], max_dlugosc=20)
        if p["numer_sluzbowy"] in numery_sluzbowe:
            bledy.append(f"{ctx}: zduplikowany numer_sluzbowy '{p['numer_sluzbowy']}'")
        numery_sluzbowe.add(p["numer_sluzbowy"])

        _sprawdz_tekst(bledy, f"{ctx}.imie", p["imie"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.nazwisko", p["nazwisko"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.stopien", p["stopien"], max_dlugosc=30, wymagany=False)

    # --- 3. WIEZNIOWIE ---
    wiezniowie_by_id: dict[int, dict[str, Any]] = {}
    numery_ewidencyjne: set[str] = set()
    uzyte_pesele: set[str] = set()

    for w in dane.wiezniowie:
        wid = w["id_wieznia"]
        ctx = f"wiezniowie(id_wieznia={wid})"
        if not isinstance(wid, int) or wid <= 0 or wid in wiezniowie_by_id:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_wieznia")
        wiezniowie_by_id[wid] = w

        _sprawdz_tekst(bledy, f"{ctx}.numer_ewidencyjny", w["numer_ewidencyjny"], max_dlugosc=20)
        if w["numer_ewidencyjny"] in numery_ewidencyjne:
            bledy.append(f"{ctx}: zduplikowany numer_ewidencyjny '{w['numer_ewidencyjny']}'")
        numery_ewidencyjne.add(w["numer_ewidencyjny"])

        _sprawdz_tekst(bledy, f"{ctx}.imie", w["imie"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.nazwisko", w["nazwisko"], max_dlugosc=50)

        data_ur = w["data_urodzenia"]
        data_przyj = w["data_przyjecia"]
        if not isinstance(data_ur, date):
            bledy.append(f"{ctx}.data_urodzenia: oczekiwano date")
        else:
            if data_ur > limit_wieku_17:
                bledy.append(f"{ctx}.data_urodzenia: {data_ur} narusza wymóg wieku >= 17 lat")
            if isinstance(data_przyj, datetime):
                limit_przy_przyjeciu = data_przyj.date() - timedelta(days=17 * 365 + 4)
                if data_ur > limit_przy_przyjeciu:
                    bledy.append(
                        f"{ctx}: wiek w dniu przyjęcia ({data_przyj.date()}) poniżej 17 lat (ur. {data_ur})"
                    )

        if not isinstance(data_przyj, datetime):
            bledy.append(f"{ctx}.data_przyjecia: oczekiwano datetime")
        elif data_przyj > teraz:
            bledy.append(f"{ctx}.data_przyjecia: data w przyszłości ({data_przyj})")

        pesel = w["pesel"]
        if pesel is None:
            bledy.append(f"{ctx}.pesel: wartość wymagana (NOT NULL), otrzymano NULL")
        elif not isinstance(pesel, str):
            bledy.append(f"{ctx}.pesel: oczekiwano str, otrzymano {type(pesel).__name__}")
        else:
            if pesel in uzyte_pesele:
                bledy.append(f"{ctx}.pesel: zduplikowany PESEL '{pesel}'")
            uzyte_pesele.add(pesel)
            if isinstance(data_ur, date):
                blad_pesel = weryfikuj_pesel(pesel, data_ur)
                if blad_pesel:
                    bledy.append(f"{ctx}: {blad_pesel}")

        if w["status"] not in STATUSY_WIEZNIOW:
            bledy.append(f"{ctx}.status: niedozwolona wartość '{w['status']}'")

    # --- 4. WYROKI ---
    wyroki_ids: set[int] = set()
    wyroki_na_wieznia: dict[int, list[dict[str, Any]]] = {wid: [] for wid in wiezniowie_by_id}

    for wyr in dane.wyroki:
        wyr_id = wyr["id_wyroku"]
        ctx = f"wyroki(id_wyroku={wyr_id})"
        if not isinstance(wyr_id, int) or wyr_id <= 0 or wyr_id in wyroki_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_wyroku")
        wyroki_ids.add(wyr_id)

        wid = wyr["id_wieznia"]
        if wid not in wiezniowie_by_id:
            bledy.append(f"{ctx}: naruszenie FK id_wieznia={wid}")
        else:
            wyroki_na_wieznia[wid].append(wyr)

        _sprawdz_tekst(bledy, f"{ctx}.sygnatura_akt", wyr["sygnatura_akt"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.sad", wyr["sad"], max_dlugosc=100)
        _sprawdz_tekst(bledy, f"{ctx}.artykul_kk", wyr["artykul_kk"], max_dlugosc=50)

        d_rozp = wyr["data_rozpoczecia"]
        d_plan = wyr["planowana_data_zakonczenia"]
        d_rzecz = wyr["rzeczywista_data_zakonczenia"]

        if d_plan < d_rozp:
            bledy.append(f"{ctx}: planowana_data_zakonczenia ({d_plan}) < data_rozpoczecia ({d_rozp})")
        if d_rzecz is not None and d_rzecz < d_rozp:
            bledy.append(f"{ctx}: rzeczywista_data_zakonczenia ({d_rzecz}) < data_rozpoczecia ({d_rozp})")

    for wid, w in wiezniowie_by_id.items():
        lista_wyr = wyroki_na_wieznia[wid]
        if not lista_wyr:
            bledy.append(f"wiezniowie(id_wieznia={wid}): brak przypisanych wyroków")
            continue
        if w["status"] == "osadzony" and not any(x["rzeczywista_data_zakonczenia"] is None for x in lista_wyr):
            bledy.append(f"wiezniowie(id_wieznia={wid}): aktywny osadzony nie ma otwartego wyroku")
        if w["status"] == "zwolniony" and any(x["rzeczywista_data_zakonczenia"] is None for x in lista_wyr):
            bledy.append(f"wiezniowie(id_wieznia={wid}): zwolniony więzień ma niezakończony wyrok")

    # --- 5. PRZYDZIALY_CEL ---
    przydzialy_ids: set[int] = set()
    przydzialy_na_wieznia: dict[int, list[dict[str, Any]]] = {wid: [] for wid in wiezniowie_by_id}
    aktywne_oblozenie: dict[int, int] = {cid: 0 for cid in cele_ids}

    for pr in dane.przydzialy_cel:
        pr_id = pr["id_przydzialu"]
        ctx = f"przydzialy_cel(id_przydzialu={pr_id})"
        if not isinstance(pr_id, int) or pr_id <= 0 or pr_id in przydzialy_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_przydzialu")
        przydzialy_ids.add(pr_id)

        wid = pr["id_wieznia"]
        cid = pr["id_celi"]
        if wid not in wiezniowie_by_id:
            bledy.append(f"{ctx}: naruszenie FK id_wieznia={wid}")
        else:
            przydzialy_na_wieznia[wid].append(pr)
            if pr["data_od"] < wiezniowie_by_id[wid]["data_przyjecia"]:
                bledy.append(f"{ctx}: data_od ({pr['data_od']}) wcześniejsza niż data_przyjecia więźnia")

        if cid not in cele_ids:
            bledy.append(f"{ctx}: naruszenie FK id_celi={cid}")

        if pr["data_od"] > teraz:
            bledy.append(f"{ctx}: data_od w przyszłości ({pr['data_od']})")
        if pr["data_do"] is not None:
            if pr["data_do"] <= pr["data_od"]:
                bledy.append(f"{ctx}: naruszenie CHECK (data_do <= data_od)")
            if pr["data_do"] > teraz:
                bledy.append(f"{ctx}: data_do w przyszłości ({pr['data_do']})")
        elif cid in aktywne_oblozenie:
            aktywne_oblozenie[cid] += 1

    # Weryfikacja indeksów częściowych, ciągłości historii i pojemności cel
    for wid, w in wiezniowie_by_id.items():
        historia = sorted(przydzialy_na_wieznia[wid], key=lambda x: x["data_od"])
        aktywne = [x for x in historia if x["data_do"] is None]
        if len(aktywne) > 1:
            bledy.append(f"wiezniowie(id_wieznia={wid}): naruszenie idx_jeden_aktywny_przydzial ({len(aktywne)})")
        if w["status"] == "osadzony" and len(aktywne) != 1:
            bledy.append(f"wiezniowie(id_wieznia={wid}): osadzony musi mieć dokładnie 1 aktywny przydział")
        if w["status"] != "osadzony" and len(aktywne) != 0:
            bledy.append(f"wiezniowie(id_wieznia={wid}): status '{w['status']}' nie może mieć otwartego przydziału")

        for prev, curr in zip(historia, historia[1:]):
            if prev["data_do"] is None or prev["data_do"] > curr["data_od"]:
                bledy.append(
                    f"wiezniowie(id_wieznia={wid}): nakładające się przydziały cel "
                    f"(id {prev['id_przydzialu']} i {curr['id_przydzialu']})"
                )

    for cid, liczba_os in aktywne_oblozenie.items():
        if liczba_os > pojemnosci_cel[cid]:
            bledy.append(
                f"cele(id_celi={cid}): przekroczono pojemność celi ({liczba_os} > {pojemnosci_cel[cid]})"
            )

    # --- 6. WIDZENIA ---
    widzenia_ids: set[int] = set()
    for wid_rec in dane.widzenia:
        vid = wid_rec["id_widzenia"]
        ctx = f"widzenia(id_widzenia={vid})"
        if not isinstance(vid, int) or vid <= 0 or vid in widzenia_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_widzenia")
        widzenia_ids.add(vid)

        wid = wid_rec["id_wieznia"]
        if wid not in wiezniowie_by_id:
            bledy.append(f"{ctx}: naruszenie FK id_wieznia={wid}")
        else:
            if wid_rec["data_widzenia"] < wiezniowie_by_id[wid]["data_przyjecia"]:
                bledy.append(f"{ctx}: data_widzenia przed datą przyjęcia więźnia")

        _sprawdz_tekst(bledy, f"{ctx}.imie_odwiedzajacego", wid_rec["imie_odwiedzajacego"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.nazwisko_odwiedzajacego", wid_rec["nazwisko_odwiedzajacego"], max_dlugosc=50)
        _sprawdz_tekst(bledy, f"{ctx}.relacja", wid_rec["relacja"], max_dlugosc=30, wymagany=False)

        if wid_rec["data_widzenia"] > teraz:
            bledy.append(f"{ctx}: data_widzenia w przyszłości ({wid_rec['data_widzenia']})")

        czas = wid_rec["czas_trwania_min"]
        if czas is not None and (not isinstance(czas, int) or not (1 <= czas <= 240)):
            bledy.append(f"{ctx}.czas_trwania_min: wartość {czas} poza zakresem (1..240)")

    # --- 7. INCYDENTY ---
    incydenty_ids: set[int] = set()
    for inc in dane.incydenty:
        iid = inc["id_incydentu"]
        ctx = f"incydenty(id_incydentu={iid})"
        if not isinstance(iid, int) or iid <= 0 or iid in incydenty_ids:
            bledy.append(f"{ctx}: niepoprawne lub zduplikowane id_incydentu")
        incydenty_ids.add(iid)

        wid = inc["id_wieznia"]
        if wid not in wiezniowie_by_id:
            bledy.append(f"{ctx}: naruszenie FK id_wieznia={wid}")
        else:
            if inc["data_zdarzenia"] < wiezniowie_by_id[wid]["data_przyjecia"]:
                bledy.append(f"{ctx}: data_zdarzenia przed datą przyjęcia więźnia")

        fid = inc["id_funkcjonariusza"]
        if fid is not None and fid not in personel_ids:
            bledy.append(f"{ctx}: naruszenie FK id_funkcjonariusza={fid}")

        if inc["data_zdarzenia"] > teraz:
            bledy.append(f"{ctx}: data_zdarzenia w przyszłości ({inc['data_zdarzenia']})")

        if inc["typ"] not in TYPY_INCYDENTOW:
            bledy.append(f"{ctx}.typ: niedozwolona wartość '{inc['typ']}'")

        _sprawdz_tekst(bledy, f"{ctx}.opis", inc["opis"], max_dlugosc=10_000, min_dlugosc=5)

    if bledy:
        raise ValidationError(bledy)


# ---------------------------------------------------------------------------
# Eksport do SQL (PostgreSQL)
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
        linie = [
            f"    ({', '.join(sql_val(row[k]) for k in kolumny)})"
            for row in paczkowane
        ]
        f.write(",\n".join(linie))
        f.write(";\n\n")


def eksportuj_sql(dane: DaneBazy, sciezka: Path) -> None:
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    with sciezka.open("w", encoding="utf-8") as f:
        f.write("-- =====================================================================\n")
        f.write("-- Dane testowe: System Ewidencji Zakładu Karnego (PostgreSQL)\n")
        f.write("-- Źródło danych osobowych: FakerAPI v2 (pl_PL)\n")
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def dodatnia_liczba(wartosc: str) -> int:
    liczba = int(wartosc)
    if liczba <= 0:
        raise argparse.ArgumentTypeError("wartość musi być większa od 0")
    return liczba


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generator danych testowych PostgreSQL dla bazy danych Zakładu Karnego."
    )
    parser.add_argument(
        "--wiezniowie", type=dodatnia_liczba, default=100,
        help="Liczba więźniów do wygenerowania (domyślnie: 100)",
    )
    parser.add_argument(
        "--personel", type=dodatnia_liczba, default=30,
        help="Liczba funkcjonariuszy do wygenerowania (domyślnie: 30)",
    )
    parser.add_argument(
        "--cele", type=dodatnia_liczba, default=40,
        help="Minimalna liczba cel do wygenerowania (domyślnie: 40)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Ziarno generatora losowego (domyślnie: 42)",
    )
    parser.add_argument(
        "--timeout", type=dodatnia_liczba, default=15,
        help="Limit czasu na zapytanie HTTP w sekundach (domyślnie: 15)",
    )
    parser.add_argument(
        "--output", type=str, default="seed_data.sql",
        help="Ścieżka wyjściowego pliku SQL dla PostgreSQL (domyślnie: seed_data.sql)",
    )
    args = parser.parse_args()

    dane = generuj_dane(
        liczba_wiezniow=args.wiezniowie,
        liczba_personelu=args.personel,
        liczba_cel=args.cele,
        seed=args.seed,
        timeout=args.timeout,
    )

    sciezka = Path(args.output)
    eksportuj_sql(dane, sciezka)

    aktywni = sum(1 for w in dane.wiezniowie if w["status"] == "osadzony")
    print("Walidacja danych zakończona pomyślnie (0 błędów).")
    print("Wygenerowano dane:")
    print(f"  - cele:           {len(dane.cele)}")
    print(f"  - personel:       {len(dane.personel)}")
    print(f"  - wiezniowie:     {len(dane.wiezniowie)} (w tym aktywni osadzeni: {aktywni})")
    print(f"  - wyroki:         {len(dane.wyroki)}")
    print(f"  - przydzialy_cel: {len(dane.przydzialy_cel)}")
    print(f"  - widzenia:       {len(dane.widzenia)}")
    print(f"  - incydenty:      {len(dane.incydenty)}")
    print(f"Zapisano do: {sciezka.resolve()}")


if __name__ == "__main__":
    main()
