#!/bin/bash
#
# Script to get the airports database

OUTFILE=${1:-ListOfAirports.csv}

curl https://davidmegginson.github.io/ourairports-data/airports.csv -o ${OUTFILE}
if [ $? -eq 0 ]; then
    echo "Wrote airports to ${OUTFILE}"
else
    echo "Command failed"
    exit 1
fi