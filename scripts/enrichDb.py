#!/usr/bin/env python3
"""
Populate missing fields in the route cache from local CSV files.

Fills airport fields (iata, name, city, country, lat, lon) from the OurAirports CSV
and the airline field from the airline codes CSV, for any routes where those fields
are NULL or empty.

Usage:
    python scripts/enrichDb.py --config config.json [--dryRun]
    python scripts/enrichDb.py --db ~/.aircraftroute/routes.db \
        --airportCsv data/AirportCodes.csv \
        --airlineCsv data/ListOfAirlineCodes.csv
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys


def loadAirports(csvPath):
    airports = {}
    with open(csvPath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            icao = row.get("ident", "").strip()
            if icao:
                airports[icao] = {
                    "iata":    row.get("iata_code", "").strip(),
                    "name":    row.get("name", "").strip(),
                    "city":    row.get("municipality", "").strip(),
                    "country": row.get("iso_country", "").strip(),
                    "lat":     float(row.get("latitude_deg") or 0.0),
                    "lon":     float(row.get("longitude_deg") or 0.0),
                }
    return airports


def loadAirlines(csvPath):
    airlines = {}
    with open(csvPath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            icao = row.get("ICAO", "").strip()
            name = row.get("Airline", "").strip()
            if icao and name:
                airlines[icao] = name
    return airlines


def callsignPrefix(callsign):
    m = re.match(r"^([A-Z]+)", callsign.strip().upper())
    return m.group(1) if m else ""


def collectAirportChanges(row, prefix, ref):
    changes = {}
    for field in ("iata", "name", "city", "country"):
        col = f"{prefix}_{field}"
        if not row[col] and ref.get(field):
            changes[col] = ref[field]
    for field in ("lat", "lon"):
        col = f"{prefix}_{field}"
        if not row[col] and ref.get(field):
            changes[col] = ref[field]
    return changes


def main():
    ap = argparse.ArgumentParser(
        description="Fill missing fields in the route cache from local CSV files."
    )
    ap.add_argument("--config",     metavar="PATH", help="config.json (source of db and csv paths)")
    ap.add_argument("--db",         metavar="PATH", help="SQLite cache file (overrides config)")
    ap.add_argument("--airportCsv", metavar="PATH", help="OurAirports CSV file (overrides config)")
    ap.add_argument("--airlineCsv", metavar="PATH", help="Airline codes CSV file (overrides config)")
    ap.add_argument("--dryRun",     action="store_true", help="Print what would change without writing")
    args = ap.parse_args()

    cfg = {}
    configDir = "."
    if args.config:
        configPath = os.path.expanduser(args.config)
        configDir = os.path.dirname(os.path.abspath(configPath))
        with open(configPath) as f:
            cfg = json.load(f)

    def resolve(path):
        if not path:
            return ""
        path = os.path.expanduser(path)
        return path if os.path.isabs(path) else os.path.join(configDir, path)

    dbPath      = resolve(args.db         or cfg.get("cacheDb")         or "~/.aircraftroute/routes.db")
    airportPath = resolve(args.airportCsv or cfg.get("airportCodesCsv") or "")
    airlinePath = resolve(args.airlineCsv or cfg.get("airlineCodesCsv") or "")

    if not airportPath and not airlinePath:
        print("ERROR: provide --airportCsv and/or --airlineCsv (or set them in config)", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(dbPath):
        print(f"ERROR: database not found: {dbPath}", file=sys.stderr)
        sys.exit(1)

    airports = {}
    if airportPath:
        if not os.path.exists(airportPath):
            print(f"ERROR: airport CSV not found: {airportPath}", file=sys.stderr)
            sys.exit(1)
        print(f"Loading airports from {airportPath} ...")
        airports = loadAirports(airportPath)
        print(f"  {len(airports)} airports loaded.")

    airlines = {}
    if airlinePath:
        if not os.path.exists(airlinePath):
            print(f"ERROR: airline CSV not found: {airlinePath}", file=sys.stderr)
            sys.exit(1)
        print(f"Loading airlines from {airlinePath} ...")
        airlines = loadAirlines(airlinePath)
        print(f"  {len(airlines)} airlines loaded.")

    conn = sqlite3.connect(dbPath)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM routes ORDER BY callsign").fetchall()
    print(f"Checking {len(rows)} cached routes ...")

    updatedRoutes = 0
    updatedFields = 0
    for row in rows:
        changes = {}

        if airports:
            for prefix in ("origin", "dest"):
                icao = row[f"{prefix}_icao"]
                if not icao:
                    continue
                ref = airports.get(icao)
                if ref:
                    changes.update(collectAirportChanges(row, prefix, ref))

        if airlines and not row["airline"]:
            prefix = callsignPrefix(row["callsign"])
            name = airlines.get(prefix, "")
            if name:
                changes["airline"] = name

        if not changes:
            continue

        updatedRoutes += 1
        updatedFields += len(changes)
        if args.dryRun:
            print(f"  {row['callsign']}: {sorted(changes.keys())}")
        else:
            set_clause = ", ".join(f"{col} = ?" for col in changes)
            conn.execute(
                f"UPDATE routes SET {set_clause} WHERE callsign = ?",
                [*changes.values(), row["callsign"]],
            )

    if not args.dryRun:
        conn.commit()
    conn.close()

    verb = "Would update" if args.dryRun else "Updated"
    print(f"{verb} {updatedRoutes}/{len(rows)} routes ({updatedFields} fields).")


if __name__ == "__main__":
    main()
