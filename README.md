# Flight Management Database Application

CM500292 Databases Coursework

## Requirements

Python 3.8 or later. No external packages needed , only the standard library (`sqlite3`, `re`, `datetime`).

## Running the application

```bash
python main.py
```

The database file `FlightManagement.db` is included in the repository. If it is missing, the application creates it automatically and loads 12 destinations, 12 pilots and 14 flights as sample data on the first run.

## Files

| File | Description |
|------|-------------|
| `main.py` | Main application — CLI menu, all SQL queries, CRUD operations |
| `FlightManagement.db` | Pre-populated SQLite database |

## Menu options

```
Flights
 1  Add a new flight
 2  View flights by criteria
 3  Update flight information
 4  Assign pilot to flight
 5  Remove pilot from flight
 6  View pilot schedule
 7  Delete a flight

Pilots
 8  Add a new pilot
 9  Update pilot details
10  Delete a pilot

Destinations
11  Manage destinations

Reports
12  Summary reports

 0  Exit
```
