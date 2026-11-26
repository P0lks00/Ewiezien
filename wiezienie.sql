-- ============================================================================
-- System Ewidencji Zakładu Karnego - Schemat Bazowy (PostgreSQL)
-- ============================================================================

BEGIN;

-- 1. Kartoteka główna osadzonych
CREATE TABLE wiezniowie (
    id_wieznia        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    numer_ewidencyjny VARCHAR(20) NOT NULL UNIQUE,
    pesel             CHAR(11) UNIQUE,
    imie              VARCHAR(50) NOT NULL,
    nazwisko          VARCHAR(50) NOT NULL,
    data_urodzenia    DATE NOT NULL,
    data_przyjecia    TIMESTAMP NOT NULL DEFAULT now(),
    status            VARCHAR(20) NOT NULL
);

COMMENT ON COLUMN wiezniowie.status IS 'Wartości: osadzony, zwolniony, przeniesiony, zbiegly, zmarly';

-- 2. Orzeczenia sądowe
CREATE TABLE wyroki (
    id_wyroku                  INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_wieznia                 INT NOT NULL,
    sygnatura_akt              VARCHAR(50) NOT NULL,
    sad                        VARCHAR(100) NOT NULL,
    artykul_kk                 VARCHAR(50) NOT NULL,
    data_rozpoczecia           DATE NOT NULL,
    planowana_data_zakonczenia DATE NOT NULL,
    rzeczywista_data_zakonczenia DATE,

    CONSTRAINT fk_wyroki_wiezien
        FOREIGN KEY (id_wieznia) REFERENCES wiezniowie (id_wieznia)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- 3. Infrastruktura zakwaterowania
CREATE TABLE cele (
    id_celi             INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    blok                VARCHAR(10) NOT NULL,
    numer_celi          VARCHAR(10) NOT NULL,
    pojemnosc           INT NOT NULL,
    poziom_zabezpieczen VARCHAR(20) NOT NULL,

    CONSTRAINT uq_cele_blok_numer UNIQUE (blok, numer_celi)
);

COMMENT ON COLUMN cele.poziom_zabezpieczen IS 'Wartości: otwarty, polotwarty, zamkniety, izolatka';

-- 4. Historia i bieżące zakwaterowanie (tabela asocjacyjna M:N)
CREATE TABLE przydzialy_cel (
    id_przydzialu INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_wieznia    INT NOT NULL,
    id_celi       INT NOT NULL,
    data_od       TIMESTAMP NOT NULL DEFAULT now(),
    data_do       TIMESTAMP,

    CONSTRAINT fk_przydzialy_wiezien
        FOREIGN KEY (id_wieznia) REFERENCES wiezniowie (id_wieznia)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_przydzialy_cela
        FOREIGN KEY (id_celi) REFERENCES cele (id_celi)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON COLUMN przydzialy_cel.data_do IS 'NULL oznacza aktualną celę';

-- 5. Kadra funkcjonariuszy
CREATE TABLE personel (
    id_funkcjonariusza INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    numer_sluzbowy     VARCHAR(20) NOT NULL UNIQUE,
    imie               VARCHAR(50) NOT NULL,
    nazwisko           VARCHAR(50) NOT NULL,
    stopien            VARCHAR(30)
);

-- 6. Rejestr zdarzeń nadzwyczajnych i nagród
CREATE TABLE incydenty (
    id_incydentu       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_wieznia         INT NOT NULL,
    id_funkcjonariusza INT,
    data_zdarzenia     TIMESTAMP NOT NULL DEFAULT now(),
    typ                VARCHAR(30) NOT NULL,
    opis               TEXT NOT NULL,

    CONSTRAINT fk_incydenty_wiezien
        FOREIGN KEY (id_wieznia) REFERENCES wiezniowie (id_wieznia)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_incydenty_funkcjonariusz
        FOREIGN KEY (id_funkcjonariusza) REFERENCES personel (id_funkcjonariusza)
        ON UPDATE CASCADE ON DELETE SET NULL
);

COMMENT ON COLUMN incydenty.typ IS 'Wartości: bojka, kontrabanda, proba_ucieczki, nagroda, inne';

-- 7. Rejestr odwiedzin
CREATE TABLE widzenia (
    id_widzenia            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_wieznia             INT NOT NULL,
    imie_odwiedzajacego    VARCHAR(50) NOT NULL,
    nazwisko_odwiedzajacego VARCHAR(50) NOT NULL,
    relacja                VARCHAR(30),
    data_widzenia          TIMESTAMP NOT NULL,
    czas_trwania_min       INT NOT NULL DEFAULT 60,

    CONSTRAINT fk_widzenia_wiezien
        FOREIGN KEY (id_wieznia) REFERENCES wiezniowie (id_wieznia)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON COLUMN widzenia.relacja IS 'np. adwokat, rodzina';

-- Indeksy na kluczach obcych dla wydajności złączeń (JOIN)
CREATE INDEX idx_wyroki_id_wieznia ON wyroki (id_wieznia);
CREATE INDEX idx_przydzialy_id_wieznia ON przydzialy_cel (id_wieznia);
CREATE INDEX idx_przydzialy_id_celi ON przydzialy_cel (id_celi);
CREATE INDEX idx_incydenty_id_wieznia ON incydenty (id_wieznia);
CREATE INDEX idx_incydenty_id_funkcjonariusza ON incydenty (id_funkcjonariusza);
CREATE INDEX idx_widzenia_id_wieznia ON widzenia (id_wieznia);

COMMIT;