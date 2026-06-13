#!/usr/bin/env python3
"""
Web API server for callsign lookup.

Exposes:
    GET /callsign/<callsign>   → JSON route info or 404

Usage:
    python callsignServer.py --config config.json [--port 5000] [--host 0.0.0.0]
"""

import argparse
import logging
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from callsignLookup import FlightInfoLookup

from flask import Flask, jsonify

log = logging.getLogger(__name__)
app = Flask(__name__)
_lookup: FlightInfoLookup = None


@app.route("/callsign/<callsign>")
def lookupCallsign(callsign: str):
    callsign = callsign.strip().upper()
    log.info("Request: %s", callsign)
    route = _lookup.lookup(callsign)
    if route is None:
        log.info("Not found: %s", callsign)
        return jsonify({"callsign": callsign, "found": False}), 404
    result = {"found": True, **asdict(route)}
    log.info("Found: %s → %s/%s",
             callsign,
             route.origin.icao if route.origin else None,
             route.destination.icao if route.destination else None)
    return jsonify(result)


def main():
    global _lookup

    p = argparse.ArgumentParser(description="Callsign lookup web API server.")
    p.add_argument("--config",       metavar="PATH", help="JSON config file")
    p.add_argument("--cache",        metavar="PATH", help="SQLite cache file (overrides config)")
    p.add_argument("--airlineCodes", metavar="PATH", help="Airline codes CSV (overrides config)")
    p.add_argument("--airportCodes", metavar="PATH", help="Airport codes CSV (overrides config)")
    p.add_argument("--cacheOnly",    action="store_true", help="Only use cache; never call cloud services")
    p.add_argument("--host",         default="0.0.0.0",  help="Bind address (default: 0.0.0.0)")
    p.add_argument("--port",         type=int, default=5000, help="Port (default: 5000)")
    p.add_argument("--logLevel",     default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Log level (default: INFO)")
    p.add_argument("--logFile",      metavar="FILE", help="Log to file instead of stdout")
    args = p.parse_args()

    handler = logging.FileHandler(args.logFile) if args.logFile else logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(args.logLevel)

    _lookup = FlightInfoLookup(
        config=args.config,
        cacheDb=args.cache,
        airlineCodesCsv=args.airlineCodes,
        airportCodesCsv=args.airportCodes,
        cacheOnly=args.cacheOnly,
    )

    log.info("Starting callsign server on %s:%s", args.host, args.port)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
