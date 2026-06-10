import sqlite3
import sys
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# main.py  –  Flight Management System
# CM500292 Databases Coursework
#
# Three entities:
#   Destinations  – airports the airline serves
#   Pilots        – crew members who operate flights
#   Flights       – scheduled services linking two destinations
#
# All SQL statements are class-level strings for easy review.
# PRAGMA foreign_keys = ON is set on every connection so the database
# rejects invalid OriginID, DestID and PilotID values at insert time.
# ---------------------------------------------------------------------------

DB_FILE = "FlightManagement.db"

# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def _valid_date(s):
    """Return True only for a real calendar date in YYYY-MM-DD format."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def _valid_time(s):
    """Return True if s is HH:MM with valid hour (0-23) and minute (0-59)."""
    m = re.fullmatch(r"(\d{2}):(\d{2})", s)
    if not m:
        return False
    return 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59

def _valid_iata(s):
    """Return True if s is exactly 3 ASCII letters."""
    return bool(re.fullmatch(r"[A-Za-z]{3}", s))

def _ask(prompt, validator=None):
    """Prompt until a non-empty, valid value is entered."""
    while True:
        raw = input(prompt).strip()
        if not raw:
            print("  Value cannot be empty – please try again.")
            continue
        if validator and not validator(raw):
            print("  Invalid format – please try again.")
            continue
        return raw

def _ask_int(prompt):
    """Prompt until a valid positive integer is entered."""
    while True:
        raw = input(prompt).strip()
        try:
            val = int(raw)
            if val > 0:
                return val
            print("  Please enter a positive number.")
        except ValueError:
            print("  Please enter a whole number.")

def _ask_optional_int(prompt):
    """Return int if the user types a number, None if they press Enter."""
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        try:
            val = int(raw)
            if val > 0:
                return val
            print("  Please enter a positive number.")
        except ValueError:
            print("  Please enter a whole number, or press Enter to skip.")

def _ask_choice(prompt, choices):
    """Prompt until user types one of the given choices (case-insensitive).
    choices can be a set of strings or a dict mapping input->value."""
    if isinstance(choices, dict):
        keys = {k.lower() for k in choices}
    else:
        keys = {c.lower() for c in choices}
    while True:
        val = input(prompt).strip().lower()
        if val in keys:
            if isinstance(choices, dict):
                return choices[val]
            return val
        print(f"  Please enter one of: {', '.join(sorted(keys))}")


# ---------------------------------------------------------------------------
# DBOperations – all database logic
# ---------------------------------------------------------------------------

class DBOperations:

    # ── DDL ──────────────────────────────────────────────────────────────

    _create_destinations = """
        CREATE TABLE IF NOT EXISTS Destinations (
            DestinationID INTEGER PRIMARY KEY AUTOINCREMENT,
            City          TEXT NOT NULL,
            Country       TEXT NOT NULL,
            Airport       TEXT NOT NULL,
            IATA_Code     TEXT NOT NULL UNIQUE
        )
    """

    _create_pilots = """
        CREATE TABLE IF NOT EXISTS Pilots (
            PilotID   INTEGER PRIMARY KEY AUTOINCREMENT,
            FirstName TEXT NOT NULL,
            LastName  TEXT NOT NULL,
            LicenceNo TEXT NOT NULL UNIQUE,
            Rank      TEXT NOT NULL
                      CHECK (Rank IN ('Captain', 'First Officer'))
        )
    """

    # PilotID nullable: flight may exist before crew is assigned.
    # Explicit FOREIGN KEY clauses are required for PRAGMA foreign_keys = ON.
    _create_flights = """
        CREATE TABLE IF NOT EXISTS Flights (
            FlightID  INTEGER PRIMARY KEY AUTOINCREMENT,
            FlightNo  TEXT    NOT NULL UNIQUE,
            OriginID  INTEGER NOT NULL,
            DestID    INTEGER NOT NULL,
            DepDate   TEXT    NOT NULL,
            DepTime   TEXT    NOT NULL,
            ArrTime   TEXT    NOT NULL,
            Status    TEXT    NOT NULL DEFAULT 'Scheduled'
                      CHECK (Status IN ('Scheduled', 'Delayed', 'Cancelled')),
            PilotID   INTEGER,
            FOREIGN KEY (OriginID) REFERENCES Destinations(DestinationID),
            FOREIGN KEY (DestID)   REFERENCES Destinations(DestinationID),
            FOREIGN KEY (PilotID)  REFERENCES Pilots(PilotID)
        )
    """

    # ── INSERT ───────────────────────────────────────────────────────────

    _ins_dest   = "INSERT INTO Destinations (City,Country,Airport,IATA_Code) VALUES (?,?,?,?)"
    _ins_pilot  = "INSERT INTO Pilots (FirstName,LastName,LicenceNo,Rank) VALUES (?,?,?,?)"
    _ins_flight = """
        INSERT INTO Flights
            (FlightNo,OriginID,DestID,DepDate,DepTime,ArrTime,Status,PilotID)
        VALUES (?,?,?,?,?,?,?,?)
    """

    # ── SELECT ───────────────────────────────────────────────────────────

    # Full flight list – dual JOIN on Destinations, LEFT JOIN on Pilots.
    _sel_all_flights = """
        SELECT f.FlightID,
               f.FlightNo,
               o.City || ' (' || o.IATA_Code || ')' AS Origin,
               d.City || ' (' || d.IATA_Code || ')' AS Destination,
               f.DepDate,
               f.DepTime,
               f.ArrTime,
               f.Status,
               COALESCE(p.FirstName || ' ' || p.LastName, 'Unassigned') AS Pilot
        FROM   Flights f
        JOIN   Destinations o ON f.OriginID = o.DestinationID
        JOIN   Destinations d ON f.DestID   = d.DestinationID
        LEFT   JOIN Pilots  p ON f.PilotID  = p.PilotID
        ORDER  BY f.DepDate, f.DepTime
    """

    # Filter by city name (partial) or exact IATA code.
    _sel_by_dest = """
        SELECT f.FlightID, f.FlightNo,
               o.City AS Origin, d.City AS Destination,
               f.DepDate, f.DepTime, f.Status
        FROM   Flights f
        JOIN   Destinations o ON f.OriginID = o.DestinationID
        JOIN   Destinations d ON f.DestID   = d.DestinationID
        WHERE  d.City LIKE ? OR d.IATA_Code = ?
        ORDER  BY f.DepDate
    """

    _sel_by_status = """
        SELECT f.FlightID, f.FlightNo,
               o.City AS Origin, d.City AS Destination,
               f.DepDate, f.DepTime, f.Status
        FROM   Flights f
        JOIN   Destinations o ON f.OriginID = o.DestinationID
        JOIN   Destinations d ON f.DestID   = d.DestinationID
        WHERE  f.Status = ?
    """

    _sel_by_date = """
        SELECT f.FlightID, f.FlightNo,
               o.City AS Origin, d.City AS Destination,
               f.DepDate, f.DepTime, f.Status
        FROM   Flights f
        JOIN   Destinations o ON f.OriginID = o.DestinationID
        JOIN   Destinations d ON f.DestID   = d.DestinationID
        WHERE  f.DepDate = ?
    """

    # Pilot schedule ordered chronologically.
    _sel_pilot_sched = """
        SELECT f.FlightNo,
               o.City AS Origin,
               d.City AS Destination,
               f.DepDate, f.DepTime, f.ArrTime, f.Status
        FROM   Flights f
        JOIN   Destinations o ON f.OriginID = o.DestinationID
        JOIN   Destinations d ON f.DestID   = d.DestinationID
        WHERE  f.PilotID = ?
        ORDER  BY f.DepDate, f.DepTime
    """

    _sel_all_pilots = """
        SELECT PilotID, FirstName, LastName, LicenceNo, Rank
        FROM   Pilots ORDER BY LastName
    """
    _sel_all_dests = """
        SELECT DestinationID, City, Country, Airport, IATA_Code
        FROM   Destinations ORDER BY City
    """

    # Aggregation: arrivals per destination.
    _agg_by_dest = """
        SELECT d.City, d.IATA_Code, COUNT(f.FlightID) AS Flights
        FROM   Destinations d
        LEFT   JOIN Flights f ON f.DestID = d.DestinationID
        GROUP  BY d.DestinationID
        ORDER  BY Flights DESC
    """

    # Aggregation: flights per pilot.
    _agg_by_pilot = """
        SELECT p.FirstName || ' ' || p.LastName AS Pilot,
               p.Rank,
               COUNT(f.FlightID) AS Flights
        FROM   Pilots p
        LEFT   JOIN Flights f ON f.PilotID = p.PilotID
        GROUP  BY p.PilotID
        ORDER  BY Flights DESC
    """

    # ── UPDATE ───────────────────────────────────────────────────────────

    _upd_status     = "UPDATE Flights SET Status  = ?                         WHERE FlightID = ?"
    _upd_schedule   = "UPDATE Flights SET DepDate = ?, DepTime = ?, ArrTime = ? WHERE FlightID = ?"
    _upd_pilot_asgn = "UPDATE Flights SET PilotID = ?                         WHERE FlightID = ?"
    _upd_dest = """
        UPDATE Destinations
        SET City=?, Country=?, Airport=?, IATA_Code=?
        WHERE DestinationID=?
    """
    _upd_pilot = """
        UPDATE Pilots
        SET FirstName=?, LastName=?, LicenceNo=?, Rank=?
        WHERE PilotID=?
    """

    # ── DELETE ───────────────────────────────────────────────────────────

    _del_flight = "DELETE FROM Flights      WHERE FlightID      = ?"
    _del_pilot  = "DELETE FROM Pilots       WHERE PilotID       = ?"
    _del_dest   = "DELETE FROM Destinations WHERE DestinationID = ?"

    # ── Initialisation ───────────────────────────────────────────────────

    def __init__(self):
        """Create the three tables on first run (no-op if they already exist)."""
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(self._create_destinations)
            conn.execute(self._create_pilots)
            conn.execute(self._create_flights)
            conn.commit()
        except sqlite3.Error as e:
            print(f"  [setup error] {e}")
            sys.exit(1)
        finally:
            if conn:
                conn.close()

    def _conn(self):
        """Open a connection with foreign key enforcement active.
        PRAGMA foreign_keys must be set per connection in SQLite."""
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ── Sample data ──────────────────────────────────────────────────────

    def load_sample_data(self):
        """Seed all three tables on first run.
        Skips only if all three tables already contain data.
        If data is partial, prints a warning and skips to avoid duplicates."""
        conn = self._conn()
        try:
            d = conn.execute("SELECT COUNT(*) FROM Destinations").fetchone()[0]
            p = conn.execute("SELECT COUNT(*) FROM Pilots").fetchone()[0]
            f = conn.execute("SELECT COUNT(*) FROM Flights").fetchone()[0]

            if d > 0 and p > 0 and f > 0:
                print("  Database already populated – skipping seed.")
                return
            if d > 0 or p > 0 or f > 0:
                print("  Warning: database contains partial data – skipping seed.")
                print("  Delete FlightManagement.db to reset.")
                return

            dests = [
                ("London",    "United Kingdom", "Heathrow Airport",             "LHR"),
                ("Istanbul",  "Turkey",          "Istanbul Airport",              "IST"),
                ("New York",  "USA",             "John F. Kennedy Intl Airport",  "JFK"),
                ("Dubai",     "UAE",             "Dubai International Airport",   "DXB"),
                ("Paris",     "France",          "Charles de Gaulle Airport",     "CDG"),
                ("Tokyo",     "Japan",           "Narita International Airport",  "NRT"),
                ("Sydney",    "Australia",       "Sydney Kingsford Smith Airport","SYD"),
                ("Frankfurt", "Germany",         "Frankfurt Airport",             "FRA"),
                ("Toronto",   "Canada",          "Toronto Pearson Intl Airport",  "YYZ"),
                ("Singapore", "Singapore",       "Singapore Changi Airport",      "SIN"),
                ("Amsterdam", "Netherlands",     "Amsterdam Airport Schiphol",    "AMS"),
                ("Cairo",     "Egypt",           "Cairo International Airport",   "CAI"),
            ]
            conn.executemany(self._ins_dest, dests)

            pilots = [
                ("James",   "Harrison", "UK-CPT-0041", "Captain"),
                ("Sarah",   "Mitchell", "UK-CPT-0087", "Captain"),
                ("David",   "Chen",     "UK-FO-0113",  "First Officer"),
                ("Emily",   "Patel",    "UK-CPT-0204", "Captain"),
                ("Michael", "Roberts",  "UK-FO-0259",  "First Officer"),
                ("Ayse",    "Yilmaz",   "TR-CPT-0312", "Captain"),
                ("Carlos",  "Gomez",    "ES-FO-0376",  "First Officer"),
                ("Hannah",  "Weber",    "DE-CPT-0418", "Captain"),
                ("Liam",    "OBrien",   "IE-FO-0465",  "First Officer"),
                ("Yuki",    "Tanaka",   "JP-CPT-0521", "Captain"),
                ("Omar",    "Hassan",   "EG-FO-0574",  "First Officer"),
                ("Priya",   "Sharma",   "IN-CPT-0633", "Captain"),
            ]
            conn.executemany(self._ins_pilot, pilots)

            # (FlightNo, OriginID, DestID, DepDate, DepTime, ArrTime, Status, PilotID)
            flights = [
                ("TK101",  1,  2,  "2025-06-10", "08:00", "13:00", "Scheduled",  1),
                ("TK202",  2,  3,  "2025-06-10", "14:30", "20:00", "Scheduled",  2),
                ("BA305",  1,  4,  "2025-06-11", "09:15", "19:45", "Scheduled",  4),
                ("EK410",  4,  6,  "2025-06-11", "22:00", "14:30", "Scheduled",  6),
                ("LH512",  8,  5,  "2025-06-12", "07:45", "09:00", "Scheduled",  8),
                ("QF615",  7,  9,  "2025-06-12", "11:20", "06:50", "Delayed",   10),
                ("SQ718", 10,  3,  "2025-06-13", "00:10", "07:30", "Scheduled", 12),
                ("AF821",  5, 11,  "2025-06-13", "16:00", "17:10", "Scheduled",  2),
                ("TK930",  2,  8,  "2025-06-14", "10:00", "12:30", "Scheduled",  1),
                ("BA035",  1,  9,  "2025-06-14", "13:45", "16:00", "Cancelled",  4),
                ("MS140", 12,  2,  "2025-06-15", "08:30", "10:00", "Scheduled", 11),
                ("TK241",  2,  5,  "2025-06-15", "17:00", "19:30", "Scheduled",  6),
                ("EK342",  4, 10,  "2025-06-16", "03:00", "13:45", "Scheduled",  3),
                ("LH443",  8,  3,  "2025-06-16", "15:00", "18:30", "Scheduled",  9),
            ]
            conn.executemany(self._ins_flight, flights)
            conn.commit()
            print("  Sample data loaded: 12 destinations, 12 pilots, 14 flights.")
        except sqlite3.Error as e:
            print(f"  [seed error] {e}")
        finally:
            conn.close()

    # ── FLIGHT operations ─────────────────────────────────────────────────

    def add_flight(self):
        """Prompt the user and insert a new flight record.
        Foreign key validity is enforced by SQLite (PRAGMA foreign_keys = ON)."""
        conn = self._conn()
        try:
            self._show_dests(conn)
            fn    = _ask("  Flight number (e.g. TK999)      : ").upper()
            oid   = _ask_int("  Origin DestinationID            : ")
            did   = _ask_int("  Destination DestinationID       : ")
            if oid == did:
                print("  Origin and destination must be different.")
                return
            date  = _ask("  Departure date (YYYY-MM-DD)     : ", _valid_date)
            dtime = _ask("  Departure time (HH:MM)          : ", _valid_time)
            atime = _ask("  Arrival time   (HH:MM)          : ", _valid_time)
            status = _ask_choice(
                "  Status – [S]cheduled / [D]elayed / [C]ancelled : ",
                {"s": "Scheduled", "d": "Delayed", "c": "Cancelled"}
            )
            self._show_pilots(conn)
            pid = _ask_optional_int("  PilotID to assign (Enter to skip): ")

            conn.execute(self._ins_flight,
                         (fn, oid, did, date, dtime, atime, status, pid))
            conn.commit()
            print(f"\n  Flight {fn} added successfully.")
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE" in msg:
                print("  Error: a flight with that number already exists.")
            elif "FOREIGN KEY" in msg:
                print("  Error: OriginID, DestinationID or PilotID does not exist in the database.")
            else:
                print(f"  Error: {e}")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def view_flights(self):
        """Retrieve flights filtered by destination, status, date, or show all."""
        print("\n  Filter:  a) Destination  b) Status  c) Date  d) All")
        choice = _ask_choice("  > ", {"a", "b", "c", "d"})
        conn = self._conn()
        try:
            if choice == "a":
                term = _ask("  City name or IATA code: ").upper()
                rows = conn.execute(self._sel_by_dest,
                                    (f"%{term}%", term)).fetchall()
                heads = ["ID", "FlightNo", "Origin", "Destination", "Date", "Dep", "Status"]
            elif choice == "b":
                status = _ask_choice(
                    "  Status – [S]cheduled / [D]elayed / [C]ancelled : ",
                    {"s": "Scheduled", "d": "Delayed", "c": "Cancelled"}
                )
                rows = conn.execute(self._sel_by_status, (status,)).fetchall()
                heads = ["ID", "FlightNo", "Origin", "Destination", "Date", "Dep", "Status"]
            elif choice == "c":
                date = _ask("  Date (YYYY-MM-DD): ", _valid_date)
                rows = conn.execute(self._sel_by_date, (date,)).fetchall()
                heads = ["ID", "FlightNo", "Origin", "Destination", "Date", "Dep", "Status"]
            else:
                rows = conn.execute(self._sel_all_flights).fetchall()
                heads = ["ID", "FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status", "Pilot"]
            print()
            self._table(heads, rows) if rows else print("  No flights found.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def update_flight(self):
        """Update a flight's status or full departure/arrival schedule."""
        conn = self._conn()
        try:
            rows = conn.execute(self._sel_all_flights).fetchall()
            self._table(["ID", "FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status", "Pilot"], rows)
            fid = _ask_int("\n  FlightID to update: ")
            print("  a) Status   b) Departure and arrival schedule")
            sub = _ask_choice("  > ", {"a", "b"})
            if sub == "a":
                status = _ask_choice(
                    "  New status – [S]cheduled / [D]elayed / [C]ancelled : ",
                    {"s": "Scheduled", "d": "Delayed", "c": "Cancelled"}
                )
                r = conn.execute(self._upd_status, (status, fid))
            else:
                nd = _ask("  New departure date (YYYY-MM-DD) : ", _valid_date)
                nt = _ask("  New departure time (HH:MM)      : ", _valid_time)
                na = _ask("  New arrival time   (HH:MM)      : ", _valid_time)
                r  = conn.execute(self._upd_schedule, (nd, nt, na, fid))
            conn.commit()
            print(f"  {r.rowcount} row(s) updated." if r.rowcount else "  Record not found.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def assign_pilot(self):
        """Assign or reassign a pilot to a flight."""
        conn = self._conn()
        try:
            rows = conn.execute(self._sel_all_flights).fetchall()
            self._table(["ID", "FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status", "Pilot"], rows)
            fid = _ask_int("\n  FlightID : ")
            self._show_pilots(conn)
            pid = _ask_int("\n  PilotID  : ")
            r   = conn.execute(self._upd_pilot_asgn, (pid, fid))
            conn.commit()
            print("  Pilot assigned." if r.rowcount else "  Flight not found.")
        except sqlite3.IntegrityError:
            print("  Error: that PilotID does not exist.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def unassign_pilot(self):
        """Remove the pilot assignment from a flight (set PilotID to NULL)."""
        conn = self._conn()
        try:
            rows = conn.execute(self._sel_all_flights).fetchall()
            self._table(["ID", "FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status", "Pilot"], rows)
            fid = _ask_int("\n  FlightID to unassign pilot from: ")
            r   = conn.execute(self._upd_pilot_asgn, (None, fid))
            conn.commit()
            print("  Pilot removed from flight." if r.rowcount else "  Flight not found.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def pilot_schedule(self):
        """Display all flights assigned to a chosen pilot."""
        conn = self._conn()
        try:
            self._show_pilots(conn)
            pid = _ask_int("\n  PilotID: ")
            row = conn.execute(
                "SELECT FirstName, LastName FROM Pilots WHERE PilotID = ?",
                (pid,)).fetchone()
            if not row:
                print("  Pilot not found.")
                return
            rows = conn.execute(self._sel_pilot_sched, (pid,)).fetchall()
            print(f"\n  Schedule – {row[0]} {row[1]}")
            self._table(["FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status"], rows) \
                if rows else print("  No flights assigned.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def delete_flight(self):
        """Delete a flight after user confirmation."""
        conn = self._conn()
        try:
            rows = conn.execute(self._sel_all_flights).fetchall()
            self._table(["ID", "FlightNo", "Origin", "Destination",
                         "Date", "Dep", "Arr", "Status", "Pilot"], rows)
            fid = _ask_int("\n  FlightID to delete: ")
            if input(f"  Confirm delete FlightID {fid}? (yes/no): ").strip().lower() == "yes":
                r = conn.execute(self._del_flight, (fid,))
                conn.commit()
                print(f"  {r.rowcount} flight(s) deleted." if r.rowcount else "  Not found.")
            else:
                print("  Cancelled.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    # ── PILOT operations ──────────────────────────────────────────────────

    def add_pilot(self):
        """Insert a new pilot record."""
        conn = self._conn()
        try:
            fn   = _ask("  First name  : ")
            ln   = _ask("  Last name   : ")
            lic  = _ask("  Licence no  : ")
            rank = _ask_choice(
                "  Rank – [C]aptain / [F]irst Officer : ",
                {"c": "Captain", "f": "First Officer"}
            )
            conn.execute(self._ins_pilot, (fn, ln, lic, rank))
            conn.commit()
            print(f"  Pilot {fn} {ln} added.")
        except sqlite3.IntegrityError:
            print("  Error: a pilot with that licence number already exists.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def update_pilot(self):
        """Update any combination of a pilot's name, licence or rank.
        Press Enter to keep the current value for any field."""
        conn = self._conn()
        try:
            self._show_pilots(conn)
            pid = _ask_int("\n  PilotID to update: ")
            row = conn.execute(
                "SELECT FirstName,LastName,LicenceNo,Rank FROM Pilots WHERE PilotID=?",
                (pid,)).fetchone()
            if not row:
                print("  Pilot not found.")
                return
            fn, ln, lic, rank = row
            print("  Press Enter to keep the current value.")
            new_fn  = input(f"  First name  [{fn}]   : ").strip() or fn
            new_ln  = input(f"  Last name   [{ln}]   : ").strip() or ln
            new_lic = input(f"  Licence no  [{lic}]  : ").strip() or lic
            while True:
                r_inp = input(f"  Rank [{rank}] – C/Captain, F/First Officer, Enter to keep: ").strip().lower()
                if r_inp == "":
                    new_rank = rank; break
                elif r_inp in ("c", "captain"):
                    new_rank = "Captain"; break
                elif r_inp in ("f", "first officer", "fo"):
                    new_rank = "First Officer"; break
                else:
                    print("  Please enter C, F, or press Enter to keep.")
            r = conn.execute(self._upd_pilot, (new_fn, new_ln, new_lic, new_rank, pid))
            conn.commit()
            print("  Pilot updated." if r.rowcount else "  Not found.")
        except sqlite3.IntegrityError:
            print("  Error: that licence number is already in use.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    def delete_pilot(self):
        """Delete a pilot only if they have no assigned flights."""
        conn = self._conn()
        try:
            self._show_pilots(conn)
            pid = _ask_int("\n  PilotID to delete: ")
            cnt = conn.execute(
                "SELECT COUNT(*) FROM Flights WHERE PilotID=?", (pid,)).fetchone()[0]
            if cnt > 0:
                print(f"  Cannot delete – pilot is assigned to {cnt} flight(s).")
                return
            if input(f"  Confirm delete PilotID {pid}? (yes/no): ").strip().lower() == "yes":
                r = conn.execute(self._del_pilot, (pid,))
                conn.commit()
                print(f"  {r.rowcount} pilot(s) deleted." if r.rowcount else "  Not found.")
            else:
                print("  Cancelled.")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    # ── DESTINATION operations ────────────────────────────────────────────

    def manage_destinations(self):
        """View, add, update or delete destinations."""
        conn = self._conn()
        try:
            rows = conn.execute(self._sel_all_dests).fetchall()
            self._table(["ID", "City", "Country", "Airport", "IATA"], rows)
            print("\n  a) Add   b) Update   c) Delete   d) Back")
            choice = _ask_choice("  > ", {"a", "b", "c", "d"})

            if choice == "a":
                city = _ask("  City    : ")
                ctry = _ask("  Country : ")
                apt  = _ask("  Airport : ")
                iata = _ask("  IATA (3 letters): ",
                             lambda s: _valid_iata(s)).upper()
                conn.execute(self._ins_dest, (city, ctry, apt, iata))
                conn.commit()
                print(f"  {city} ({iata}) added.")

            elif choice == "b":
                did = _ask_int("  DestinationID to update: ")
                row = conn.execute(
                    "SELECT City,Country,Airport,IATA_Code FROM Destinations WHERE DestinationID=?",
                    (did,)).fetchone()
                if not row:
                    print("  Destination not found.")
                    return
                city, ctry, apt, iata = row
                print("  Press Enter to keep the current value.")
                new_city = input(f"  City    [{city}] : ").strip() or city
                new_ctry = input(f"  Country [{ctry}] : ").strip() or ctry
                new_apt  = input(f"  Airport [{apt}]  : ").strip() or apt
                raw_iata = input(f"  IATA    [{iata}] : ").strip()
                if raw_iata and not _valid_iata(raw_iata):
                    print("  Invalid IATA code – keeping original.")
                    raw_iata = iata
                new_iata = raw_iata.upper() if raw_iata else iata
                r = conn.execute(self._upd_dest,
                                 (new_city, new_ctry, new_apt, new_iata, did))
                conn.commit()
                print("  Updated." if r.rowcount else "  Not found.")

            elif choice == "c":
                did = _ask_int("  DestinationID to delete: ")
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM Flights WHERE OriginID=? OR DestID=?",
                    (did, did)).fetchone()[0]
                if cnt > 0:
                    print(f"  Cannot delete – referenced by {cnt} flight(s).")
                    return
                if input(f"  Confirm delete DestinationID {did}? (yes/no): ").strip().lower() == "yes":
                    r = conn.execute(self._del_dest, (did,))
                    conn.commit()
                    print(f"  {r.rowcount} destination(s) deleted." if r.rowcount else "  Not found.")
                else:
                    print("  Cancelled.")

        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                print("  Error: that IATA code is already in use.")
            else:
                print(f"  Error: {e}")
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    # ── REPORTS ───────────────────────────────────────────────────────────

    def summary_reports(self):
        """Aggregated flight counts per destination and per pilot."""
        conn = self._conn()
        try:
            print("\n  -- Arrivals per destination --")
            self._table(["City", "IATA", "Flights"],
                        conn.execute(self._agg_by_dest).fetchall())
            print("\n  -- Flights per pilot --")
            self._table(["Pilot", "Rank", "Flights"],
                        conn.execute(self._agg_by_pilot).fetchall())
        except sqlite3.Error as e:
            print(f"  Error: {e}")
        finally:
            conn.close()

    # ── Display helpers ───────────────────────────────────────────────────

    def _show_pilots(self, conn):
        print("\n  -- Pilots --")
        self._table(["ID", "First", "Last", "Licence", "Rank"],
                    conn.execute(self._sel_all_pilots).fetchall())

    def _show_dests(self, conn):
        print("\n  -- Destinations --")
        self._table(["ID", "City", "Country", "Airport", "IATA"],
                    conn.execute(self._sel_all_dests).fetchall())

    def _table(self, headers, rows):
        """Print rows as an aligned table with dynamic column widths."""
        if not rows:
            print("  (no records)"); return
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell) if cell is not None else "-"))
        fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
        print(fmt.format(*headers))
        print("  " + "  ".join("-" * w for w in widths))
        for row in rows:
            print(fmt.format(*[str(c) if c is not None else "-" for c in row]))


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def main():
    db = DBOperations()
    db.load_sample_data()

    menu = """
  --------------------------------------------------
   Flight Management System  -  CM500292
  --------------------------------------------------
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
  --------------------------------------------------"""

    dispatch = {
        1:  db.add_flight,          2:  db.view_flights,
        3:  db.update_flight,       4:  db.assign_pilot,
        5:  db.unassign_pilot,      6:  db.pilot_schedule,
        7:  db.delete_flight,       8:  db.add_pilot,
        9:  db.update_pilot,        10: db.delete_pilot,
        11: db.manage_destinations, 12: db.summary_reports,
    }

    while True:
        print(menu)
        try:
            choice = int(input("  Choice: "))
        except ValueError:
            print("  Please enter a number."); continue
        if choice == 0:
            print("  Goodbye."); break
        elif choice in dispatch:
            dispatch[choice]()
        else:
            print("  Invalid option (0-12).")


if __name__ == "__main__":
    main()
