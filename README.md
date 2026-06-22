# AircraftRoute

Aircraft callsign to route lookup tools that services hits out of a local, persistant, cache, and misses from a list of web-API services.
This includes a local web-server that offers callsign to route lookups.

---
## callsignLookup.py: script to get route information for a given callsign

A module that, given an aircraft callsign (e.g. `AAL1599`), returns the airline name and route (origin + destination airports with ICAO codes, names, cities, countries, and coordinates).

### Files

```
config.example.json      # copy to config.json and fill in API keys
scripts/
  aircraftInfo.sh        # tool to get information about a given aircraft
  callsignLookup.py      # main module — importable library + CLI
  callsignServer.py      # Flask web API server
  getAirlineCodes.py     # script to get mapping of airline codes to names
data/
  AirlineCodes.csv       # Wikipedia airline codes table (IATA, ICAO, Airline, ...)
  AirportCodes.csv       # Airport codes table (IATA, ICAO, lat, lon, country, ...)
requirements.txt       # requests, flask
```

---

### Architecture

```
callsign
  │
  ▼
RouteCache (SQLite)  ──hit──▶  FlightRoute
  │
 miss
  │
  ▼
Service chain (in order, skip unavailable)
  1. AviationStack
  2. OpenSky
  3. AirLabs
  4. AeroDataBox
  5. FlightAware (last because it will auto-charge if you exceed your monthly quota)
  │
  ▼
Airline name fallback: prefix match against data/AirlineCodes.csv
  │
  ▼
RouteCache.put() + return FlightRoute
```

A service is marked unavailable for the session when it returns a rate-limit signal. Services are used in order until one succeeds or all are exhausted. "Not found" from a service is not fatal; the next service is tried.

Services are tried in order. A service is skipped for the remainder of the session when it returns a rate-limit signal. Any service that returns no route (not found, partial, or error) causes the next service to be tried. The loop stops only when a service returns a route with both origin and destination, or all services are exhausted.

If no service returns a complete route but the callsign prefix matches a known ICAO airline code, a partial `FlightRoute` (airline name, no airports) is returned but not cached.

---

### Cache

SQLite file, default `~/.AircraftRoute/routes.db`. Created automatically. Schema:

```sql
CREATE TABLE routes (
    callsign       TEXT PRIMARY KEY,
    airline        TEXT,
    origin_icao    TEXT,  origin_iata    TEXT,  origin_name    TEXT,
    origin_city    TEXT,  origin_country TEXT,  origin_lat     REAL,  origin_lon     REAL,
    dest_icao      TEXT,  dest_iata      TEXT,  dest_name      TEXT,
    dest_city      TEXT,  dest_country   TEXT,  dest_lat       REAL,  dest_lon       REAL,
    cached_at      TEXT
);
```

Existing databases are migrated automatically on startup (`ALTER TABLE ADD COLUMN` for the `iata` columns).

The cache is permanent (no TTL). Use `--flushCache` to clear all rows.

Only routes with both origin and destination populated are written to the cache. Airline-only results (no airports) are returned to the caller but not persisted.

---

### Aircraft Infomation Services

It turns out that even the paid services are fairly inaccurate when it comes to providing the routes for an aircraft with a given callsign.

#### Details of the different services

The online services with the most accurate route information are (in order of accuracy) are as follows:

##### 1. FlightConnections
????
Best for scheduled airline routes (most accurate route maps), 900+ airlines, no realtime positions, not for tracking
Free tier is available
????

##### 2. FlightRadar24 (FR24)
????
very good route information (based on FAA flight plans and ADS-B data)
best live tracking service, better than FlightAware
paid service
????

##### 3. FlightAware (AeroAPI): `https://aeroapi.flightaware.com/aeroapi/`
????
Paid, expensive, realtime positions
good data quality (95% commercial accuracy), with occasional mistakes in routes
swaps origin and destination sometimes
????

????
- Auth: `x-apikey` header
- Route: `GET /flights/{callsign}`
- Rate limit signal: HTTP 429

##### 4. AviationStack: `https://api.aviationstack.com/v1/`
????
schedules and flight status information
good data quality, multi-source backbone
global coverage
limited realtime information
paid, free tier available
strong for schedules and origin/destination information
????

Must create an account.
100 req/month free.
- Auth: `?access_key=` query param
- Route: `GET /flights?flight_icao={callsign}`
- Rate limit signals: HTTP 429 or `{"error": {"code": "usage_limit_reached"}}`

##### 5. AirLabs: `https://airlabs.co/api/v9/`
????
Best free-tier option for direct route lookup.
mid-market, realtime information, good quality data
paid service with free tier
global coverage
popular developer API
????

Must create a (free) account at `https://airlabs.co`.
- Auth: `?api_key=` query param
- Route: `GET /flights?flight_icao={callsign}` → `dep_icao`, `arr_icao`
- Airport detail: `GET /airports?icao_code={code}` → name, city, country, lat, lng
- Rate limit signals: response body `{"error": {"message": "minute_limit_exceeded"|"hour_limit_exceeded"|"month_limit_exceeded"}}`

##### 6. AeroDataBox: `https://aerodatabox.p.rapidapi.com`
????
site for budget lookups
reasonable quality, not global coverage, limited realtime positions
Paid, free tier available
????
Must create a (free) account at `https://rapidapi.com` and go to get a key for the AeroDataBox API.
~500 req/month free via RapidAPI.
- Auth: `X-RapidAPI-Key` header
- Route: `GET /flights/callsign/{callsign}`
- Rate limit signals: HTTP 429, or `X-RateLimit-Requests-Remaining: 0`

##### 7. OpenSky: `https://opensky-network.org/api`
????
inferred data only (from ADS-B tracks, not schedules)
only historical data
Free tier available
????

400 credits/day free. No direct callsign→route API; route is estimated from trajectory.
- Auth: OAuth2 Bearer token (30-min TTL, refreshed automatically), or anonymous
- Step 1: `GET /states/all` (no callsign filter exists server-side) → fetch all current states and match
  the requested callsign against each state vector's `callsign` field client-side → ICAO24 hex
- Step 2: `GET /flights/aircraft?icao24={hex}&begin=...&end=...` → estimated departure/arrival airports
  for the flight whose `callsign` matches exactly; no match → no result (never guesses from a different flight)
- Rate limit signal: HTTP 429; HTTP 401 triggers token refresh

---

### Config file

`config.json` (copy from `config.example.json`):

```json
{
  "cacheDb": "~/.AircraftRoute/routes.db",
  "airlineCodesCsv": "data/AirlineCodes.csv",
  "airportCodesCsv": "data/ListOfAirports.csv",
  "services": [
    { "name": "airLabs",       "enabled": true,  "apiKey": "<key>",        "requestDelay": 1.0 },
    { "name": "aeroDataBox",   "enabled": false, "rapidApiKey": "",        "requestDelay": 1.0 },
    { "name": "flightAware",   "enabled": false, "apiKey": "",             "requestDelay": 0.5 },
    { "name": "aviationStack", "enabled": false, "apiKey": "",             "requestDelay": 2.0 },
    { "name": "openSky",       "enabled": false, "username": "", "password": "", "requestDelay": 5.0 }
  ]
}
```

Paths in the config are resolved relative to the config file's directory. `~` is expanded.
CLI flags override config values.

`requestDelay` (seconds, default `0.0`) is the minimum pause after each call to that service. Applied after every attempt — hit, miss, or error — so consecutive calls during `--fillCache` don't exceed the service's rate limit. Suggested starting values are shown above; tune to your plan's actual limits.

---

### CLI

```
# Single lookup
python callsignLookup.py AAL1599 --config config.json

# Lookup without a config (airline name only from CSV, no route)
python callsignLookup.py AAL1599 --airlineCodes data/AirlineCodes.csv

# Pass API key directly
python callsignLookup.py AAL1599 --airLabsKey YOUR_KEY

# Cache-only lookup (no cloud service calls)
python callsignLookup.py AAL1599 --cacheOnly --config config.json

# Bulk lookup using only the cache (never calls services, even on miss)
python callsignLookup.py --fillCache callsigns.txt --cacheOnly --config config.json

# Bulk-populate cache from a file of callsigns (one per line)
python callsignLookup.py --fillCache data/callsigns.txt --config config.json

# Print all cached routes
python callsignLookup.py --dumpCache --config config.json

# Delete all cached routes
python callsignLookup.py --flushCache --config config.json

# Enable debug logging to stdout
python callsignLookup.py AAL1599 --config config.json --logLevel DEBUG

# Log to a file
python callsignLookup.py AAL1599 --config config.json --logLevel DEBUG --logFile lookup.log
```

Exit code 0 on success, 1 on not-found.

All CLI flags:

| Flag | Description |
|------|-------------|
| `--config PATH` | JSON config file (auto-detected as `config.json` if present) |
| `--cache PATH` | SQLite cache file (overrides config) |
| `--airlineCodes PATH` | Airline codes CSV (overrides config) |
| `--airportCodes PATH` | OurAirports CSV for IATA code and name enrichment (overrides config) |
| `--airLabsKey KEY` | AirLabs API key |
| `--aeroDataBoxKey KEY` | AeroDataBox RapidAPI key |
| `--flightAwareKey KEY` | FlightAware API key |
| `--aviationStackKey KEY` | AviationStack API key |
| `--openSkyUser USER` | OpenSky username |
| `--openSkyPass PASS` | OpenSky password |
| `--dumpCache` | Print all cached routes and exit |
| `--flushCache` | Delete all cached routes and exit |
| `--fillCache FILE` | Bulk-populate cache from callsign list |
| `--cacheOnly` | Only consult the cache; never call cloud services (applies to `--fillCache` too) |
| `--logLevel LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `WARNING`) |
| `--logFile FILE` | Write logs to a file instead of stdout |

---

### Using as a library

```python
import sys
sys.path.insert(0, "${HOME}/Code/AircraftRoute")
from callsignLookup import FlightInfoLookup, FlightRoute, Airport

# From a config file
lookup = FlightInfoLookup(config="${HOME}/Code/AircraftRoute/config.json")

# Or fully programmatic
lookup = FlightInfoLookup(
    cacheDb="~/.AircraftRoute/routes.db",
    airlineCodesCsv="${HOME}/Code/AircraftRoute/data/AirlineCodes.csv",
    airportCodesCsv="${HOME}/Code/AircraftRoute/data/ListOfAirports.csv",
    services=[
        {"name": "airLabs", "enabled": True, "apiKey": "YOUR_KEY"},
    ],
)

route = lookup.lookup("AAL1599")
# FlightRoute(
#   callsign="AAL1599",
#   airline="American Airlines",
#   origin=Airport(icao="KDFW", iata="DFW", name="Dallas Fort Worth Intl", ...),
#   destination=Airport(icao="KLAX", iata="LAX", name="Los Angeles Intl", ...),
# )

# Cache-only mode (applies to all lookups including fillCache)
lookup = FlightInfoLookup(config="...", cacheOnly=True)
route = lookup.lookup("AAL1599")  # returns None on miss, never calls services

# Or override per-call (does not affect fillCache)
route = lookup.lookup("AAL1599", cacheOnly=True)

# Dump all cached routes
routes = lookup.dumpCache()  # returns list[FlightRoute]

# Bulk cache fill
lookup.fillCache("/path/to/callsigns.txt")

# Flush cache
lookup.flushCache()
```

`FlightRoute.origin` and `FlightRoute.destination` are `None` when no route data is available (airline-only result). Check before accessing airport fields.

`Airport.iata` is populated from the service API response where available (AirLabs, AeroDataBox, FlightAware, AviationStack all return IATA codes). For services that don't provide IATA (OpenSky), or to fill in any gaps, pass `airportCodesCsv` pointing to the OurAirports CSV (generated by `scripts/getAirportCodes.sh`). The CSV is keyed by ICAO `ident` and also enriches missing `name`, `city`, `country`, `lat`, and `lon` fields.

Only routes with both `origin` and `destination` are written to the cache. Airline-only results are returned to the caller but not persisted, so a subsequent call will re-query services.

---

## callsignServer.py: Web API server

`callsignServer.py` wraps `FlightInfoLookup` in a Flask HTTP server accessible to any machine on the LAN.

```
# Start the server
python scripts/callsignServer.py --config config.json [--port 5000] [--host 0.0.0.0]

# Optional flags (same as callsignLookup.py)
  --cache PATH       SQLite cache file
  --airlineCodes PATH
  --cacheOnly        Never call cloud services
  --logLevel LEVEL   DEBUG / INFO / WARNING / ERROR (default: INFO)
  --logFile FILE
```

### Endpoints

#### `GET /callsign/<callsign>` — route lookup

```bash
curl http://localhost:5000/callsign/UAL2409
```

**Response — found (HTTP 200):**
```json
{
  "found": true,
  "callsign": "UAL2409",
  "airline": "United Airlines",
  "origin":      { "icao": "CYYC", "iata": "YYC", "name": "Calgary Int'l", "city": "Calgary", "country": "CA", "lat": 51.11, "lon": -114.02 },
  "destination": { "icao": "KSFO", "iata": "SFO", "name": "San Francisco Int'l", "city": "San Francisco", "country": "US", "lat": 37.62, "lon": -122.38 }
}
```

`origin` and `destination` are `null` when no route data is available (airline-only result).

**Response — not found (HTTP 404):**
```json
{ "found": false, "callsign": "INVALID999" }
```

Non-commercial callsigns (e.g. `N551SJ`) return 404 immediately without calling any cloud service.

---

#### `GET /debug/<callsign>` — per-service lookup breakdown

Tries every non-disabled, non-rate-limited service and returns all results. Does not cache.

```bash
curl http://localhost:5000/debug/AAL1599
```

```json
{
  "callsign": "AAL1599",
  "cacheHit": false,
  "cacheResult": null,
  "services": [
    { "name": "aviationStack", "status": "skipped", "reason": "rateLimited" },
    { "name": "airLabs",       "status": "found",   "result": { "callsign": "AAL1599", ... } },
    { "name": "aeroDataBox",   "status": "notFound" }
  ]
}
```

Service `status` values: `found` | `partial` | `notFound` | `rateLimited` | `unavailable` | `error` | `skipped`.
`skipped` includes a `reason` field: `disabled` or `rateLimited`.

---

#### `GET /services` — service access statistics

Per-service call counts and timestamps for the current server session.

```bash
curl http://localhost:5000/services
```

```json
[
  {
    "name": "aviationStack", "enabled": true, "available": false, "requestDelay": 2.0,
    "calls": 42, "found": 18, "notFound": 12, "partial": 0,
    "rateLimitErrors": 1, "unavailableErrors": 0, "otherErrors": 11,
    "lastCall": "2026-06-14T09:12:04",
    "lastSuccessfulCall": "2026-06-14T08:54:11",
    "lastRateLimit": "2026-06-14T08:55:22"
  }
]
```

Timestamps are `null` if the event has not occurred this session.

---

#### `GET /services/status` — service enablement state

Lightweight view: current `enabled` and `available` state for each service.

```bash
curl http://localhost:5000/services/status
```

```json
[
  { "name": "aviationStack", "enabled": true,  "available": false },
  { "name": "openSky",       "enabled": true,  "available": true  },
  { "name": "airLabs",       "enabled": false, "available": true  }
]
```

`enabled` — user-controlled (persists until server restart).
`available` — cleared automatically when a service returns a rate-limit signal; restored when the service is re-enabled.

---

#### `POST /services/<name>` — enable or disable a service

```bash
# Disable a service
curl -X POST http://localhost:5000/services/openSky \
     -H "Content-Type: application/json" \
     -d '{"enabled": false}'

# Re-enable a service (also clears rate-limit flag)
curl -X POST http://localhost:5000/services/airLabs \
     -H "Content-Type: application/json" \
     -d '{"enabled": true}'
```

**Response (HTTP 200):**
```json
{ "name": "airLabs", "enabled": true }
```

**Response — unknown service (HTTP 404):**
```json
{ "error": "unknown service: 'badName'" }
```

Service names: `airLabs`, `aeroDataBox`, `flightAware`, `aviationStack`, `openSky`.

### Setting up the callsign to route lookup webserver

1. Copy the unit file to systemd
```bash
sudo cp ${HOME}/Code/AircraftRoute/etc/systemd/system/callsignServer.service \
  /etc/systemd/system/callsignServer.service
```

2. Reload systemd so it picks up the new unit
```bash
sudo systemctl daemon-reload
```

3. Enable it to start on boot
```bash
sudo systemctl enable callsignServer
```

4. Start it now
```bash
sudo systemctl start callsignServer
```

5. Verify it's running
```bash
sudo systemctl status callsignServer
```

Check the logs to make sure nothing is unhappy:
```bash
journalctl -u callsignServer -f
```
Make sure the venv exists at ${HOME}/Code/AircraftRoute/venv/ before starting; if not, create it first:
```bash
cd ${HOME}/Code/AircraftRoute
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

---

## aircraftInfo.sh: script to get information about an aircraft given its ICAO24 code

Takes a single arg (the aircraft of interest's 24-bit hex code) and returns a JSON object with information about the given aircraft.
This uses the OpenSky free web API.

Returned JSON object example:
```json
{
  "registration": "N13110",
  "manufacturerName": "Boeing",
  "manufacturerIcao": "BOEING",
  "model": "757-224",
  "typecode": "B752",
  "serialNumber": "27300",
  "lineNumber": "",
  "icaoAircraftClass": "L2J",
  "selCal": "",
  "operator": "",
  "operatorCallsign": "UNITED",
  "operatorIcao": "UAL",
  "operatorIata": "",
  "owner": "United Airlines Inc",
  "categoryDescription": "",
  "registered": null,
  "regUntil": "2027-10-31",
  "status": "",
  "built": null,
  "firstFlightDate": null,
  "engines": "ROLLS-ROYC RB-211 SERIES",
  "modes": false,
  "adsb": false,
  "acars": false,
  "vdl": false,
  "notes": "",
  "country": "United States",
  "lastSeen": null,
  "firstSeen": null,
  "icao24": "a0817c",
  "timestamp": "2023-03-23T19:00:00.000Z"
}
```

---

## getAirlineCodes.py: Script to fetch the airline codes table from Wikipedia and write it to a CSV file

Takes a path to where the .csv file is to be written as the only argument, gets the web page html, reads it in using pandas, and writes it out using pandas.

This populates the `./data` directory with the AirlineCodes.csv file that is given to callsignLookup.py (either on the command line or via its config file).

```bash
python ./scripts/getAirlineCodes.py ./data/AirlineCodes.csv
```

---

## lookupCallsigns.py: Script to look up the airline names for a list of callsigns

This script takes as args, the path to a file containing one or more callsigns (one string per line), a path to the airline codes .csv file, and a path to where the output .csv file should be written. It looks up each callsign's airline in the airline codes file, and writes an output .csv-format file with the callsign, the name of the airline, and its ICAO Airline Code.

Example input file contents:
```csv
AAL2426
AAL2430
WJA1504
WUP948
XAA2202
XAAIG
XSN06
```

Example use:
```bash
python scripts/lookupCallsigns.py callsigns.txt ./data/ListOfAirlineCodes.csv outfile.csv
Processed 7 callsigns, 5 matched (2 unmatched)
Written to outfile.csv
```

Example output file contents:
```csv
callsign,airline,airlineCode
AAL2426,American Airlines,AAL
AAL2430,American Airlines,AAL
WJA1504,WestJet,WJA
WUP948,,WUP
XAA2202,Aeronautical Radio Inc,XAA
XAAIG,,XAAIG
XSN06,Stephenville Aviation Services,XSN
```

---

## getAirportCodes.sh: Script to get database of airports

A script to get information about airports and put into a .csv file.
This should also be updated periodically.

Do this once at initial setup time.
```bash
./scripts/getAirportCodes.sh ./data/AirportCodes.csv
```

Example contents of the .csv file.
```csv
"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code","gps_code","local_code","home_link","wikipedia_link","keywords"
6523,"00A","heliport","Total RF Heliport",40.070985,-74.933689,11,"NA","US","US-PA","Bensalem","no",,,"K00A","00A","https://www.penndot.pa.gov/TravelInPA/airports-pa/Pages/Total-RF-Heliport.aspx",,
323361,"00AA","small_airport","Aero B Ranch Airport",38.704022,-101.473911,3435,"NA","US","US-KS","Leoti","no",,,"00AA","00AA",,,
6524,"00AK","small_airport","Lowell Field",59.947733,-151.692524,450,"NA","US","US-AK","Anchor Point","no",,,"00AK","00AK",,,
6525,"00AL","small_airport","Epps Airpark",34.86479949951172,-86.77030181884766,820,"NA","US","US-AL","Harvest","no",,,"00AL","00AL",,,

```

---
