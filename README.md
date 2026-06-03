# 🔌 Charging Station Scraper

Web scraper pro automatické sledování nabíjecích stanic v České republice z API fdrive.cz.

## 📋 Obsah

- [Funkce](#-funkce)
- [Instalace](#-instalace)
- [Konfigurace](#️-konfigurace)
- [Použití](#-použití)
- [Testování](#-testování)
- [Deployment](#-deployment)
- [Struktura projektu](#-struktura-projektu)

## ✨ Funkce

- **API Scraping:**
  - Stahování dat z fdrive.cz API
  - Automatické parsování GeoJSON dat
  - Validace dat před importem
  
- **MongoDB integrace:**
  - Automatický incremental update (pouze změněná data)
  - Full import možnost (kompletní reimport)
  - Import logging (automatické zaznamenávání všech operací)
  - Podpora pro více kolekcí:
    - `charging_stations` - Hlavní data o stanicích
    - `charging_providers` - Poskytovatelé
    - `charging_manufacturers` - Výrobci
    - `charging_charger_types` - Typy nabíječek
    - `charging_payment_methods` - Platební metody
  
- **Validace:**
  - Kontrola povinných polí
  - Validace GPS souřadnic
  - Kontrola datových typů
  - Detekce chybných záznamů

- **Automatizace:**
  - Google Cloud Run deployment
  - Naplánované týdenní spouštění
  - Docker kontejnerizace

## 🔧 Instalace

### Požadavky

- Python 3.10+
- MongoDB Atlas účet (nebo lokální MongoDB)
- pip

### Kroky instalace

```bash
# 1. Přejdi do složky projektu
cd Charging_station_scraper

# 2. Vytvoření virtuálního prostředí
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# nebo
venv\Scripts\activate     # Windows

# 3. Instalace závislostí
pip install -r requirements.txt

# 4. Konfigurace prostředí
cp env.example .env
nano .env  # Vyplň MongoDB credentials
```

## ⚙️ Konfigurace

### .env soubor

```bash
# MongoDB konfigurace
MONGODB_URI=mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=fueldb

# Collection Names (volitelné)
CHARGING_STATIONS_COLLECTION=charging_stations
PROVIDERS_COLLECTION=charging_providers
MANUFACTURERS_COLLECTION=charging_manufacturers
CHARGER_TYPES_COLLECTION=charging_charger_types
PAYMENT_METHODS_COLLECTION=charging_payment_methods

# API URL (volitelné)
CHARGING_STATIONS_API_URL=https://fdrive.cz/data/export/pub/charging-stations-geo.json

# Prostředí
ENVIRONMENT=development
LOG_LEVEL=INFO
```

### MongoDB Collections

- **charging_stations** - Hlavní data o nabíjecích stanicích
- **charging_providers** - Poskytovatelé (ČEZ, PRE, E.ON, atd.)
- **charging_manufacturers** - Výrobci nabíječek (ABB, Tesla, atd.)
- **charging_charger_types** - Typy nabíječek (Typ 2, CCS, CHAdeMO, atd.)
- **charging_payment_methods** - Platební metody

## 🚀 Použití

### Základní příkazy

```bash
# Test připojení k MongoDB
python test/test_connection.py

# Vytvoření indexů (doporučeno před prvním importem)
python main.py --task create_indexes
# nebo
python test/create_indexes.py

# Incremental scraping (aktualizace pouze změněných dat)
python main.py --task scrape

# Full import (smaže a reimportuje všechna data)
python main.py --task scrape_full

# Test připojení
python main.py --task test_connection
```

### Dostupné úlohy

| Příkaz | Popis | Čas běhu |
|--------|-------|----------|
| `create_indexes` | Vytvoření indexů pro všechny kolekce | ~1 sek |
| `scrape` | Incremental update (aktualizace změněných dat) | ~2-5 min |
| `scrape_full` | Full reimport všech dat | ~5-10 min |
| `test_connection` | Test MongoDB připojení | ~1 sek |

### Environment variables pro runtime

```bash
# Full import přes env variable
FULL_IMPORT=true python main.py --task scrape
```

## 🧪 Testování

### Lokální testování před deploymentem

```bash
# 1. Test MongoDB připojení
python test/test_connection.py

# 2. Vytvoření indexů (doporučeno před prvním importem)
python main.py --task create_indexes

# 3. Test scrapingu (incremental)
python main.py --task scrape

# 4. Test full importu
python main.py --task scrape_full
```

### Očekávané výstupy

```
📊 Import Results:
   stations:
      ➕ Inserted: 150
      🔄 Updated: 1200
      ⏭️ Skipped: 50
   providers:
      ➕ Inserted: 0
      🔄 Updated: 25
   manufacturers:
      ➕ Inserted: 0
      🔄 Updated: 53
   charger_types:
      ➕ Inserted: 0
      🔄 Updated: 10
   payment_methods:
      ➕ Inserted: 0
      🔄 Updated: 6
```

## 🐳 Deployment

### Google Cloud Run

#### Příprava

```bash
# Autentifikace
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

#### Automatický deployment

```bash
# Build a push Docker image
docker build -t gcr.io/YOUR_PROJECT_ID/charging-station-scraper:latest .
docker push gcr.io/YOUR_PROJECT_ID/charging-station-scraper:latest

# Deploy Cloud Run Job
gcloud run jobs replace deploy/gcloud/cloud-run-job.yaml --region=europe-west1
```

#### Nastavení Cloud Scheduler (týdenní spouštění - každé pondělí v 6:00 CET)

```bash
gcloud scheduler jobs create http charging-station-scraper-weekly \
    --schedule="0 6 * * 1" \
    --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/YOUR_PROJECT_ID/jobs/charging-station-scraper-weekly:run" \
    --http-method=POST \
    --oauth-service-account-email="YOUR_PROJECT_ID@appspot.gserviceaccount.com" \
    --location=europe-west1 \
    --time-zone="Europe/Prague"
```

### Monitoring

```bash
# Zobrazení logů
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=charging-station-scraper-weekly' --limit=50

# Manuální spuštění
gcloud run jobs execute charging-station-scraper-weekly --region=europe-west1

# Status scheduleru
gcloud scheduler jobs list --location=europe-west1
```

## 📁 Struktura projektu

```
Charging_station_scraper/
├── main.py                          # Hlavní orchestrátor
├── config.py                        # Konfigurace a env variables
├── logger.py                        # Logging setup
├── scraper.py                       # API scraper
├── validators.py                    # Data validace
│
├── database/                        # Databázová vrstva
│   ├── __init__.py
│   ├── mongodb_import.py           # MongoDB import logika
│   └── import_logger.py            # Import logging
│
├── test/                            # Testovací skripty
│   ├── __init__.py
│   ├── test_connection.py          # Test MongoDB připojení
│   └── create_indexes.py           # Vytvoření indexů
│
├── deploy/                          # Deployment soubory
│   ├── docker/                     # Docker konfigurace
│   │   └── docker-entrypoint.sh   # Docker entrypoint
│   └── gcloud/                     # Google Cloud konfigurace
│       └── cloud-run-job.yaml     # Cloud Run Job konfigurace
│
├── Dockerfile                       # Docker image
├── requirements.txt                 # Python závislosti
├── env.example                      # Template .env souboru
└── README.md                        # Tato dokumentace
```

## 📊 Data Flow

```
API (fdrive.cz)
    ↓
Data Fetching & Parsing
    ↓
Validation
    ↓
MongoDB Import (incremental/full)
    ↓
Statistics & Logging
```

## ⚠️ Důležité: Incremental vs Full Import

### Incremental Import (default - `scrape`)
- ✅ **NESMAŽE** existující data
- ✅ Aktualizuje pouze změněné záznamy
- ✅ Přidá nové záznamy
- ✅ Přeskočí nezměněné záznamy
- ✅ **Bezpečné pro pravidelný automatický import**

### Full Import (`scrape_full`)
- ⚠️ **SMAŽE VŠECHNA DATA** v kolekcích
- ⚠️ Reimportuje všechna data znovu
- ⚠️ Použij pouze při:
  - Prvním importu
  - Opravě dat
  - Změně struktury dat
- ❌ **NEPOUŽÍVEJ pro pravidelný automatický import!**

### Pravidelné spouštění (Cloud Scheduler)
Pro týdenní automatické aktualizace použij **incremental import** (`scrape`), který:
- Neztratí žádná data
- Aktualizuje pouze změněné stanice
- Přidá nové stanice
- Je rychlejší než full import

## 📇 MongoDB Indexy

Kolekce se vytvářejí automaticky při prvním insertu, ale indexy je potřeba vytvořit explicitně pro lepší výkon:

### Vytvoření indexů

```bash
# Přes main.py
python main.py --task create_indexes

# Nebo přímo
python test/create_indexes.py
```

### Vytvořené indexy

**charging_stations:**
- `station_id` (unique) - Pro rychlé vyhledávání podle ID
- `location.coordinates` (2dsphere) - Pro geografické dotazy
- `status` - Pro filtrování podle stavu
- `fast_charging` - Pro filtrování rychlého nabíjení
- `providers` - Pro filtrování podle poskytovatele
- `import_timestamp` - Pro řazení podle data importu

**charging_providers:**
- `provider_id` (unique)

**charging_manufacturers:**
- `manufacturer_id` (unique)

**charging_charger_types:**
- `charger_type_id` (unique)

**charging_payment_methods:**
- `payment_method_id` (unique)

## 🔐 Bezpečnost

- **NIKDY** necommituj `.env` soubor
- MongoDB credentials v Google Secret Manager pro production
- Používej `.gitignore` pro citlivé soubory
- Pravidelně rotuj API klíče

## 🐛 Troubleshooting

### Chyba připojení k MongoDB
```bash
# Zkontroluj .env
cat .env | grep MONGODB_URI

# Test připojení
python test/test_connection.py
```

### Scraper timeout
```bash
# Zvyš timeout v cloud-run-job.yaml
timeoutSeconds: 3600  # 1 hodina
```

### Memory limit
```bash
# Zvyš paměť v cloud-run-job.yaml
memory: "2Gi"
cpu: "1"
```

## 📞 Support

Pro problémy a otázky vytvoř issue na GitHub.

---

**Vytvořeno s ❤️ pro sledování nabíjecích stanic v ČR**

