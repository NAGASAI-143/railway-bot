from __future__ import annotations

from datetime import date, datetime
from difflib import get_close_matches
from io import BytesIO
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from flask import Flask, jsonify, redirect, render_template, request, session, send_file, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "railsmart-secret")

ROOT = Path(__file__).resolve().parent

STATIONS = {
    "HYB": "Hyderabad (HYB)",
    "SC": "Secunderabad Jn (SC)",
    "NDLS": "New Delhi (NDLS)",
    "BCT": "Mumbai Central (BCT)",
    "MMCT": "Mumbai Central (MMCT)",
    "CSMT": "Chhatrapati Shivaji Maharaj Terminus (CSMT)",
    "MAS": "Chennai Central (MAS)",
    "SBC": "KSR Bengaluru (SBC)",
    "PUNE": "Pune Jn (PUNE)",
    "ERS": "Ernakulam Jn (ERS)",
    "HWH": "Howrah Jn (HWH)",
    "LKO": "Lucknow NR (LKO)",
    "BZA": "Vijayawada Jn (BZA)",
    "PAT": "Patna Jn (PAT)",
}

TRAINS = [
    {"number": "12723", "name": "Andhra Pradesh Express", "from": "HYB", "to": "NDLS", "dep": "06:10", "arr": "09:40", "duration": "27h 30m", "classes": ["1A", "2A", "3A", "SL"]},
    {"number": "12951", "name": "Mumbai Rajdhani", "from": "NDLS", "to": "BCT", "dep": "16:55", "arr": "08:35", "duration": "15h 40m", "classes": ["1A", "2A", "3A"]},
    {"number": "12626", "name": "Kerala Express", "from": "NDLS", "to": "ERS", "dep": "05:10", "arr": "13:25", "duration": "32h 15m", "classes": ["1A", "2A", "3A", "SL"]},
    {"number": "12628", "name": "Karnataka Express", "from": "NDLS", "to": "SBC", "dep": "20:15", "arr": "05:45", "duration": "33h 30m", "classes": ["1A", "2A", "3A", "SL"]},
    {"number": "12656", "name": "Navjeevan Express", "from": "MAS", "to": "BCT", "dep": "09:40", "arr": "18:50", "duration": "33h 10m", "classes": ["2A", "3A", "SL"]},
]

FARE_RANGES = {
    "SL": (400, 1200),
    "3A": (1000, 2800),
    "2A": (1500, 4000),
    "1A": (3000, 7000),
    "CC": (700, 1800),
    "EC": (1200, 2600),
    "2S": (200, 700),
}

QUOTAS = {"GN": "General", "TQ": "Tatkal", "LD": "Ladies", "SS": "Senior"}

COMMON_CORRECTIONS = {
    "pnar": "pnr",
    "pnrr": "pnr",
    "staus": "status",
    "statsu": "status",
    "avilability": "availability",
    "availablity": "availability",
    "avaibility": "availability",
    "avaliable": "available",
    "tickt": "ticket",
    "tiket": "ticket",
    "bok": "book",
    "boook": "book",
    "trian": "train",
    "journy": "journey",
    "tatkal": "tatkal",
    "genral": "general",
    "ladys": "ladies",
    "walet": "wallet",
    "walllet": "wallet",
    "rwallet": "r-wallet",
    "wht": "what",
    "frm": "from",
    "tomorow": "tomorrow",
    "sleper": "sleeper",
    "sliper": "sleeper",
    "hyderbad": "hyderabad",
    "hydrabad": "hyderabad",
}

DOMAIN_TERMS = {
    "book",
    "booking",
    "ticket",
    "tickets",
    "train",
    "trains",
    "pnr",
    "status",
    "live",
    "running",
    "availability",
    "available",
    "seat",
    "fare",
    "price",
    "cost",
    "cancel",
    "journey",
    "travel",
    "from",
    "to",
    "today",
    "tomorrow",
    "general",
    "tatkal",
    "ladies",
    "senior",
    "class",
    "classes",
    "passenger",
    "passengers",
    "veg",
    "non-veg",
    "upi",
    "card",
    "wallet",
    "r-wallet",
    "pay",
    "payment",
    "hyderabad",
    "secunderabad",
    "delhi",
    "mumbai",
    "chennai",
    "bengaluru",
    "bangalore",
    "pune",
    "ernakulam",
    "howrah",
    "lucknow",
    "vijayawada",
    "patna",
}

for code, station_name in STATIONS.items():
    DOMAIN_TERMS.add(code.lower())
    for token in re.findall(r"[a-z]+", station_name.lower()):
        if len(token) > 2:
            DOMAIN_TERMS.add(token)


def _resolve_db_path() -> Path:
    env_db_path = os.getenv("RAILSMART_DB_PATH")
    if env_db_path:
        return Path(env_db_path)
    try:
        probe = ROOT / ".railsmart_write_check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return ROOT / "railsmart_pro.db"
    except OSError:
        return Path(tempfile.gettempdir()) / "railsmart_pro.db"


DB_PATH = _resolve_db_path()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    conn = _get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pnr TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    conn.commit()
    conn.close()


_init_db()


def _normalize_station(value: str) -> str:
    value = value.strip().upper()
    if value in STATIONS:
        return value
    for code, name in STATIONS.items():
        if value in name.upper():
            return code
    return value


def _autocorrect_message(text: str) -> str:
    corrected_parts: List[str] = []
    for part in re.split(r"(\W+)", text):
        if not part or not re.search(r"[A-Za-z]", part):
            corrected_parts.append(part)
            continue
        if "@" in part:
            corrected_parts.append(part)
            continue

        lowered = part.lower()
        replacement = COMMON_CORRECTIONS.get(lowered)
        if not replacement and len(lowered) >= 3:
            matches = get_close_matches(lowered, DOMAIN_TERMS, n=1, cutoff=0.84)
            replacement = matches[0] if matches else None

        if not replacement or replacement == lowered:
            corrected_parts.append(part)
            continue

        if part.isupper():
            corrected_parts.append(replacement.upper())
        elif part.istitle():
            corrected_parts.append(replacement.title())
        else:
            corrected_parts.append(replacement)
    return "".join(corrected_parts)


def _parse_date(text: str) -> date | None:
    text = text.strip()
    lowered = text.lower()
    today = datetime.now().date()
    if "today" in lowered:
        return today
    if "day after tomorrow" in lowered:
        return today.fromordinal(today.toordinal() + 2)
    if "tomorrow" in lowered:
        return today.fromordinal(today.toordinal() + 1)
    for pattern in (
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{2}-\d{2}-\d{4}\b",
    ):
        match = re.search(pattern, text)
        if match:
            text = match.group(0)
            break
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_pnr(text: str) -> str | None:
    match = re.search(r"(?:pnr\D*)?(\d{10})", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_train_number(text: str) -> str | None:
    match = re.search(r"\b(\d{5})\b", text)
    return match.group(1) if match else None


def _detect_intent(text: str) -> str | None:
    lowered = text.lower()
    if "cancel" in lowered:
        return "cancel"
    if "pnr" in lowered:
        return "pnr"
    if "fare" in lowered or "price" in lowered or "cost" in lowered:
        return "fare"
    if "live" in lowered or "running status" in lowered:
        return "live"
    if "availability" in lowered or "seat available" in lowered or "seat availability" in lowered:
        return "availability"
    if (
        "book" in lowered
        or "ticket" in lowered
        or (("go" in lowered or "travel" in lowered or "journey" in lowered) and "from" in lowered and "to" in lowered)
        or ("from" in lowered and "to" in lowered and "train" in lowered)
    ):
        return "book"
    return None


def _extract_station_pair(text: str) -> Tuple[str | None, str | None]:
    lowered = text.lower()
    match = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+on\b|\s+for\b|\s+tomorrow\b|\s+today\b|$)", lowered)
    if not match:
        return None, None
    origin = _normalize_station(match.group(1).strip())
    destination = _normalize_station(match.group(2).strip())
    if origin not in STATIONS or destination not in STATIONS:
        return None, None
    return origin, destination


def _parse_quota(text: str) -> str | None:
    lowered = text.lower()
    if "tatkal" in lowered or "tq" in lowered:
        return "TQ"
    if "general" in lowered or "gn" in lowered:
        return "GN"
    if "ladies" in lowered:
        return "LD"
    if "senior" in lowered:
        return "SS"
    return None


def _parse_class(text: str) -> str | None:
    cleaned = text.strip().upper().replace(" ", "")
    if cleaned in FARE_RANGES:
        return cleaned
    if "AC1" in cleaned or "FIRSTAC" in cleaned:
        return "1A"
    if "AC2" in cleaned or "SECONDAC" in cleaned:
        return "2A"
    if "AC3" in cleaned or "THIRDAC" in cleaned:
        return "3A"
    if "SLEEPER" in cleaned:
        return "SL"
    if "SECOND" in cleaned:
        return "2S"
    if "CHAIR" in cleaned:
        return "CC"
    if "EXECUTIVE" in cleaned:
        return "EC"
    return None


def _extract_classes(text: str) -> List[str]:
    classes: List[str] = []
    patterns = [
        r"\b1\s*a\b",
        r"\b2\s*a\b",
        r"\b3\s*a\b",
        r"\bac\s*1\b",
        r"\bac\s*2\b",
        r"\bac\s*3\b",
        r"\bsl\b",
        r"\bsleeper\b",
        r"\b2\s*s\b",
        r"\bsecond\s+sitting\b",
        r"\bcc\b",
        r"\bchair\s+car\b",
        r"\bec\b",
        r"\bexecutive\s+chair\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            travel_class = _parse_class(match)
            if travel_class:
                classes.append(travel_class)
    if classes:
        return list(dict.fromkeys(classes))
    fallback = [_parse_class(part) for part in re.split(r"[, ]+", text)]
    return list(dict.fromkeys([item for item in fallback if item]))


def _parse_passenger(text: str) -> Tuple[str | None, int | None, str | None, str | None]:
    normalized = re.sub(r"\s+", " ", text).strip()
    parts = [p.strip() for p in re.split(r"[,/]", normalized) if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in normalized.split(" ") if p.strip()]
    if len(parts) < 3:
        return None, None, None, None
    name_parts: List[str] = []
    age = None
    gender = None
    food = "Veg"
    for part in parts:
        lowered = part.lower()
        if part.isdigit():
            age = int(part)
        elif lowered in {"m", "male"}:
            gender = "M"
        elif lowered in {"f", "female"}:
            gender = "F"
        elif lowered in {"o", "other"}:
            gender = "O"
        elif "non" in lowered:
            food = "Non-veg"
        elif "veg" in lowered:
            food = "Veg"
        else:
            name_parts.append(part)
    name = " ".join(name_parts).strip()
    return name or None, age, gender, food


def _estimate_fare(travel_class: str) -> int:
    low, high = FARE_RANGES.get(travel_class, (600, 1800))
    return int((low + high) / 2)


def _generate_pnr() -> str:
    return f"PNR{secrets.randbelow(10**9):09d}"


def _get_user(username: str) -> sqlite3.Row | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT id, username, email, password_hash FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    return row


def _get_user_id(username: str) -> int | None:
    row = _get_user(username)
    if not row:
        return None
    return int(row["id"])


def _log_email(user_id: int, email: str, subject: str, body: str) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO email_log (user_id, email, subject, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, subject, body, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def _store_booking(user_id: int, pnr: str, payload: Dict[str, Any]) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO bookings (user_id, pnr, payload, created_at) VALUES (?, ?, ?, ?)",
        (user_id, pnr, json.dumps(payload), datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def _get_user_bookings(username: str) -> List[Dict[str, Any]]:
    user_id = _get_user_id(username)
    if not user_id:
        return []
    conn = _get_db()
    rows = conn.execute(
        "SELECT pnr, payload, created_at FROM bookings WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    bookings: List[Dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payload["created_at"] = row["created_at"]
            bookings.append(payload)
    return bookings


def _get_booking_by_pnr(username: str, pnr: str) -> Dict[str, Any] | None:
    for booking in _get_user_bookings(username):
        if booking.get("pnr") == pnr:
            return booking
    return None


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_ticket_pdf(booking: Dict[str, Any], username: str) -> bytes:
    train = booking.get("train", {})
    passengers = booking.get("passengers", [])
    passenger_names = ", ".join(
        f"{p.get('name', 'Passenger')} ({p.get('age', '-')}/{p.get('gender', '-')})"
        for p in passengers
    ) or "Passenger details unavailable"
    lines = [
        "RailSmart e-Ticket",
        "Indian Railways Style Passenger Ticket",
        f"Passenger: {username}",
        f"PNR: {booking.get('pnr', '-')}",
        f"Train: {train.get('number', '-')} {train.get('name', '-')}",
        f"From: {booking.get('from', '-')}    To: {booking.get('to', '-')}",
        f"Journey Date: {booking.get('journey_date', '-')}",
        f"Class: {booking.get('class', '-')}    Quota: {booking.get('quota', '-')}",
        f"Departure: {train.get('dep', '--:--')}    Arrival: {train.get('arr', '--:--')}",
        f"Passengers: {passenger_names}",
        f"Fare: Rs {booking.get('fare', '-')}",
        f"Payment: {booking.get('payment_method', '-')}",
        "Status: CONFIRMED",
    ]
    content_lines = ["BT", "/F1 12 Tf", "50 760 Td"]
    first = True
    for line in lines:
        prefix = "" if first else "0 -20 Td "
        content_lines.append(f"{prefix}({_pdf_escape(line)}) Tj")
        first = False
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: List[bytes] = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
    )
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append(
        f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
        + stream
        + b"\nendstream endobj\n"
    )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)


def _ollama_reply(message: str, username: str | None = None) -> str | None:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.getenv("OLLAMA_MODEL", "").strip()

    try:
        with urlrequest.urlopen(f"{host.rstrip('/')}/api/tags", timeout=5) as resp:
            tags_payload = json.loads(resp.read().decode("utf-8"))
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "Ollama is not reachable right now. Start Ollama and try again."

    models = tags_payload.get("models") or []
    if not models:
        return "Ollama is running, but no model is installed yet. Pull a model like llama3.2 and try again."

    if not model:
        model = str(models[0].get("name") or "").strip()
    if not model:
        return "Ollama is available, but I could not detect a usable model."

    prompt = (
        "You are RailSmart, a railway booking assistant. "
        "Keep replies concise and practical. "
        "If the user asks about trains, tickets, PNR, seat availability, fares, or cancellations, "
        "answer in the context of an Indian rail booking assistant. "
        "Do not claim real-time data you do not have. "
        f"User: {username or 'Guest'}\n"
        f"Message: {message}"
    )
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
    ).encode("utf-8")
    req = urlrequest.Request(
        f"{host.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            error_message = str(error_payload.get("error") or "").strip()
        except (json.JSONDecodeError, OSError):
            error_message = ""
        if error_message:
            return f"Ollama error: {error_message}"
        return "Ollama returned an error while generating the reply."
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "Ollama did not finish the response. Try again in a moment."

    reply = str(payload.get("response") or "").strip()
    return reply or "Ollama returned an empty reply."


def _run_irctc_bridge(command: str, *args: str) -> Dict[str, Any] | None:
    script_path = ROOT / "irctc_bridge.mjs"
    if not script_path.exists():
        return None

    node_cmd = os.getenv("NODE_CMD", r"C:\Program Files\nodejs\node.exe")
    try:
        completed = subprocess.run(
            [node_cmd, str(script_path), command, *args],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


@app.route("/")
def home():
    if session.get("user"):
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = _get_user(username)
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = user["username"]
            return redirect(url_for("chat"))
        error = "Invalid credentials."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not username or not password or not email:
            error = "Username, email and password are required."
        else:
            conn = _get_db()
            try:
                conn.execute(
                    "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (
                        username,
                        email,
                        generate_password_hash(password),
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                conn.commit()
                session["user"] = username
                return redirect(url_for("chat"))
            except sqlite3.IntegrityError:
                error = "Username already exists."
            finally:
                conn.close()
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect(url_for("login"))
    session.pop("chat_state", None)
    session.pop("pending_booking", None)
    bookings = _get_user_bookings(session["user"])
    return render_template("chat.html", user=session["user"], bookings=bookings)


@app.route("/api/chat", methods=["POST"])
def chat_api():
    if "user" not in session:
        return jsonify({"reply": "Please log in to start chatting."})

    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Please type a message to continue."})

    if message == "__reset__" or "reset" in message.lower():
        session.pop("chat_state", None)
        session.pop("pending_booking", None)
        return jsonify({"reply": "Chat reset. What would you like to do next?"})

    state = session.get("chat_state")
    if not state:
        state = {"mode": None, "step": None, "data": {}}

    skip_autocorrect_steps = {"passenger_details", "upi_id", "confirm"}
    corrected_message = (
        message
        if state.get("step") in skip_autocorrect_steps
        else _autocorrect_message(message)
    )
    lowered = corrected_message.lower()
    detected_intent = _detect_intent(corrected_message)
    extracted_pnr = _extract_pnr(corrected_message)
    extracted_train = _extract_train_number(corrected_message)
    extracted_date = _parse_date(corrected_message)
    extracted_from, extracted_to = _extract_station_pair(corrected_message)

    def set_mode(mode: str, step: str, reply: str):
        state["mode"] = mode
        state["step"] = step
        state.setdefault("data", {})
        session["chat_state"] = state
        return jsonify({"reply": reply})

    if state.get("mode") and detected_intent and detected_intent != state.get("mode"):
        state = {"mode": None, "step": None, "data": {}}
        session.pop("chat_state", None)
        session.pop("pending_booking", None)

    if not state.get("mode"):
        if detected_intent == "pnr" and extracted_pnr:
            bridge = _run_irctc_bridge("pnr", extracted_pnr)
            if bridge and bridge.get("success") and bridge.get("reply"):
                return jsonify({"reply": bridge["reply"]})
            if bridge and bridge.get("error"):
                return jsonify({"reply": f"PNR lookup unavailable: {bridge['error']}"})
            return jsonify({"reply": f"PNR status for {extracted_pnr}: CNF / Coach B2 / Berth 40."})
        if detected_intent == "live" and extracted_train:
            bridge = _run_irctc_bridge("live", extracted_train)
            if bridge and bridge.get("success") and bridge.get("reply"):
                return jsonify({"reply": bridge["reply"]})
            if bridge and bridge.get("error"):
                return jsonify({"reply": f"Live status unavailable right now: {bridge['error']}"})
            return jsonify({"reply": f"Train {extracted_train}: Running 25 min late. ETA 20:40."})
        if detected_intent == "fare":
            classes = _extract_classes(corrected_message)
            if classes:
                rows = [f"{c}: Rs {_estimate_fare(c)}" for c in classes]
                return jsonify({"reply": "Fare summary\n" + "\n".join(dict.fromkeys(rows))})
            return set_mode("fare", "classes", "Which classes? Example: SL, 3A, 2A")
        if detected_intent == "cancel":
            if extracted_pnr:
                return jsonify({"reply": f"Cancellation for {extracted_pnr} initiated. Refund in 3-5 days."})
            return set_mode("cancel", "pnr", "Share the PNR to cancel.")
        if detected_intent == "availability" and extracted_from and extracted_to:
            state["mode"] = "availability"
            state["data"] = {"from": extracted_from, "to": extracted_to}
            if extracted_date:
                state["data"]["date"] = extracted_date.isoformat()
                state["step"] = "class"
                session["chat_state"] = state
                return jsonify({"reply": "Class filter? (1A/2A/3A/SL/CC/EC/2S) or type 'skip'"})
            state["step"] = "date"
            session["chat_state"] = state
            return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
        if detected_intent == "book" and extracted_from and extracted_to:
            state["mode"] = "book"
            state["data"] = {"from": extracted_from, "to": extracted_to}
            if extracted_date:
                state["data"]["date"] = extracted_date.isoformat()
                state["step"] = "quota"
                session["chat_state"] = state
                return jsonify({"reply": "Booking type? (General/Tatkal/Ladies/Senior)"})
            state["step"] = "date"
            session["chat_state"] = state
            return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
        if detected_intent == "book":
            return set_mode("book", "from", "Great! From which station?")
        if detected_intent == "pnr":
            return set_mode("pnr", "pnr", "Please share your PNR number.")
        if detected_intent == "availability":
            return set_mode("availability", "from", "Starting station?")
        if detected_intent == "live":
            return set_mode("live", "train", "Train number for live status?")
        reply = _ollama_reply(corrected_message, session.get("user"))
        if reply:
            return jsonify({"reply": reply})
        return jsonify(
            {
                "reply": (
                    "I can help with booking, PNR status, seat availability, live status, "
                    "fare comparison, cancellations, and e-catering. Try: 'Book ticket'."
                )
            }
        )

    mode = state.get("mode")
    step = state.get("step")
    data = state.setdefault("data", {})

    if mode == "pnr":
        session.pop("chat_state", None)
        bridge = _run_irctc_bridge("pnr", corrected_message.strip())
        if bridge and bridge.get("success") and bridge.get("reply"):
            return jsonify({"reply": bridge["reply"]})
        if bridge and bridge.get("error"):
            return jsonify({"reply": f"PNR lookup unavailable: {bridge['error']}"})
        return jsonify({"reply": f"PNR status for {corrected_message.strip()}: CNF / Coach B2 / Berth 40."})

    if mode == "live":
        train_number = re.sub(r"\D", "", corrected_message)
        if not train_number:
            return jsonify({"reply": "Please share a valid train number."})
        session.pop("chat_state", None)
        bridge = _run_irctc_bridge("live", train_number)
        if bridge and bridge.get("success") and bridge.get("reply"):
            return jsonify({"reply": bridge["reply"]})
        if bridge and bridge.get("error"):
            return jsonify({"reply": f"Live status unavailable right now: {bridge['error']}"})
        return jsonify({"reply": f"Train {train_number}: Running 25 min late. ETA 20:40."})

    if mode == "fare":
        classes = _extract_classes(corrected_message)
        if not classes:
            return jsonify({"reply": "Please share classes like SL, 3A, 2A."})
        rows = [f"{c}: Rs {_estimate_fare(c)}" for c in classes]
        session.pop("chat_state", None)
        return jsonify({"reply": "Fare summary\n" + "\n".join(rows)})

    if mode == "availability":
        if step == "from":
            if extracted_from and extracted_to:
                data["from"] = extracted_from
                data["to"] = extracted_to
                if extracted_date:
                    data["date"] = extracted_date.isoformat()
                    state["step"] = "class"
                    session["chat_state"] = state
                    return jsonify({"reply": "Class filter? (1A/2A/3A/SL/CC/EC/2S) or type 'skip'"})
                state["step"] = "date"
                session["chat_state"] = state
                return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
            data["from"] = _normalize_station(corrected_message)
            state["step"] = "to"
            session["chat_state"] = state
            return jsonify({"reply": "Destination station?"})
        if step == "to":
            if extracted_from and extracted_to:
                data["from"] = extracted_from
                data["to"] = extracted_to
                if extracted_date:
                    data["date"] = extracted_date.isoformat()
                    state["step"] = "class"
                    session["chat_state"] = state
                    return jsonify({"reply": "Class filter? (1A/2A/3A/SL/CC/EC/2S) or type 'skip'"})
                state["step"] = "date"
                session["chat_state"] = state
                return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
            data["to"] = _normalize_station(corrected_message)
            state["step"] = "date"
            session["chat_state"] = state
            return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
        if step == "date":
            journey_date = _parse_date(corrected_message)
            if not journey_date:
                return jsonify({"reply": "Please share a valid date (e.g., 2026-03-20)."})
            data["date"] = journey_date.isoformat()
            state["step"] = "class"
            session["chat_state"] = state
            return jsonify({"reply": "Class filter? (1A/2A/3A/SL/CC/EC/2S) or type 'skip'"})
        if step == "class":
            travel_class = None if "skip" in lowered else _parse_class(corrected_message)
            if corrected_message.strip() and "skip" not in lowered and not travel_class:
                return jsonify({"reply": "Please choose a valid class or type 'skip'."})
            travel_class = travel_class or "SL"
            bridge = _run_irctc_bridge(
                "availability",
                data["train"]["number"] if "train" in data else TRAINS[0]["number"],
                data["from"],
                data["to"],
                data["date"],
                travel_class,
                "GN",
            )
            if bridge and bridge.get("success") and bridge.get("reply"):
                session.pop("chat_state", None)
                return jsonify({"reply": bridge["reply"]})
            if bridge and bridge.get("error"):
                session.pop("chat_state", None)
                return jsonify({"reply": f"Availability lookup unavailable right now: {bridge['error']}"})
            result = [
                t for t in TRAINS if t["from"] == data["from"] and t["to"] == data["to"]
            ]
            lines = [
                f"{t['number']} {t['name']} {t['dep']}->{t['arr']} ({', '.join(t['classes'])})"
                for t in (result or TRAINS[:3])
            ]
            session.pop("chat_state", None)
            return jsonify({"reply": "Available trains:\n" + "\n".join(lines)})

    if mode == "cancel":
        session.pop("chat_state", None)
        return jsonify({"reply": f"Cancellation for {corrected_message.strip()} initiated. Refund in 3-5 days."})

    if mode == "book":
        if step == "from":
            if extracted_from and extracted_to:
                data["from"] = extracted_from
                data["to"] = extracted_to
                bridge = _run_irctc_bridge("search", data["from"], data["to"])
                if bridge and bridge.get("success") and bridge.get("trains"):
                    data["suggested_trains"] = bridge["trains"]
                if extracted_date:
                    data["date"] = extracted_date.isoformat()
                    state["step"] = "quota"
                    session["chat_state"] = state
                    return jsonify({"reply": "Booking type? (General/Tatkal/Ladies/Senior)"})
                state["step"] = "date"
                session["chat_state"] = state
                return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
            data["from"] = _normalize_station(corrected_message)
            state["step"] = "to"
            session["chat_state"] = state
            return jsonify({"reply": "Destination station?"})
        if step == "to":
            if extracted_from and extracted_to:
                data["from"] = extracted_from
                data["to"] = extracted_to
            else:
                data["to"] = _normalize_station(corrected_message)
            bridge = _run_irctc_bridge("search", data["from"], data["to"])
            if bridge and bridge.get("success") and bridge.get("trains"):
                data["suggested_trains"] = bridge["trains"]
            state["step"] = "date"
            session["chat_state"] = state
            return jsonify({"reply": "Journey date? (YYYY-MM-DD or DD/MM/YYYY)"})
        if step == "date":
            journey_date = _parse_date(corrected_message)
            if not journey_date:
                return jsonify({"reply": "Please share a valid date (e.g., 2026-03-20)."})
            data["date"] = journey_date.isoformat()
            state["step"] = "quota"
            session["chat_state"] = state
            return jsonify({"reply": "Booking type? (General/Tatkal/Ladies/Senior)"})
        if step == "quota":
            quota = _parse_quota(corrected_message)
            if not quota:
                return jsonify({"reply": "Please choose General, Tatkal, Ladies, or Senior."})
            data["quota"] = quota
            state["step"] = "class"
            session["chat_state"] = state
            return jsonify({"reply": "Seat class? (1A/2A/3A/SL/CC/EC/2S)"})
        if step == "class":
            travel_class = _parse_class(corrected_message)
            if not travel_class:
                return jsonify({"reply": "Please choose a valid class like 3A, SL, or 2S."})
            data["class"] = travel_class
            if data.get("suggested_trains"):
                suggested = data["suggested_trains"][0]
                data["train"] = {
                    "number": suggested.get("number", TRAINS[0]["number"]),
                    "name": suggested.get("name", TRAINS[0]["name"]),
                    "from": data["from"],
                    "to": data["to"],
                    "dep": suggested.get("departure", "--:--"),
                    "arr": suggested.get("arrival", "--:--"),
                    "duration": suggested.get("duration", ""),
                    "classes": suggested.get("classes", [travel_class]),
                }
            else:
                available = [
                    t for t in TRAINS if t["from"] == data["from"] and t["to"] == data["to"]
                ]
                data["train"] = (available or TRAINS)[0]
            state["step"] = "passengers_count"
            session["chat_state"] = state
            return jsonify({"reply": "How many passengers? (1-6)"})
        if step == "passengers_count":
            try:
                count = int(re.sub(r"\D", "", corrected_message) or "0")
            except ValueError:
                count = 0
            if count < 1 or count > 6:
                return jsonify({"reply": "Please share passenger count between 1 and 6."})
            data["passenger_count"] = count
            data["passengers"] = []
            state["step"] = "passenger_details"
            session["chat_state"] = state
            return jsonify({"reply": "Passenger 1 details (Name, Age, Gender M/F/O, Food Veg/Non-veg)."})
        if step == "passenger_details":
            name, age, gender, food = _parse_passenger(message)
            if not name or age is None or gender is None:
                return jsonify({"reply": "Please share details like: Aarav, 29, M, Veg."})
            data["passengers"].append(
                {"name": name, "age": age, "gender": gender, "food": food or "Veg"}
            )
            idx = len(data["passengers"])
            if idx < data["passenger_count"]:
                session["chat_state"] = state
                return jsonify({"reply": f"Passenger {idx + 1} details?"})
            state["step"] = "payment"
            session["chat_state"] = state
            fare = _estimate_fare(data["class"]) * data["passenger_count"]
            data["fare"] = fare
            return jsonify({"reply": f"Total fare Rs {fare}. Choose payment method (UPI/Card/R-Wallet)."})
        if step == "payment":
            method = corrected_message.strip().lower()
            if method not in {"upi", "card", "r-wallet", "wallet", "rwallet"}:
                return jsonify({"reply": "Please choose UPI, Card, or R-Wallet."})
            data["payment_method"] = "R-Wallet" if "wallet" in method else method.upper() if method == "upi" else "Card"
            if method == "upi":
                state["step"] = "upi_id"
                session["chat_state"] = state
                return jsonify({"reply": "Please enter your UPI ID (example: name@bank)."})
            state["step"] = "confirm"
            session["chat_state"] = state
            token = secrets.token_hex(8)
            session["pending_booking"] = {"token": token, "data": data}
            return jsonify(
                {
                    "reply": "Payment ready. Click 'Pay Now' to confirm.",
                    "action": {
                        "type": "payment",
                        "token": token,
                        "amount": data["fare"],
                        "method": data["payment_method"],
                    },
                }
            )
        if step == "upi_id":
            upi_id = message.strip()
            if "@" not in upi_id or len(upi_id) < 5:
                return jsonify({"reply": "Please enter a valid UPI ID like name@bank."})
            data["upi_id"] = upi_id
            state["step"] = "confirm"
            session["chat_state"] = state
            token = secrets.token_hex(8)
            session["pending_booking"] = {"token": token, "data": data}
            return jsonify(
                {
                    "reply": "Payment ready. Click 'Pay Now' to confirm.",
                    "action": {
                        "type": "payment",
                        "token": token,
                        "amount": data["fare"],
                        "method": data["payment_method"],
                    },
                }
            )

    return jsonify({"reply": "I didn’t understand that. Type 'reset' to start over."})


@app.route("/api/pay", methods=["POST"])
def pay_api():
    if "user" not in session:
        return jsonify({"reply": "Please log in to continue."}), 401
    payload = request.get_json(silent=True) or {}
    token = payload.get("token")
    pending = session.get("pending_booking")
    if not pending or pending.get("token") != token:
        return jsonify({"reply": "Payment session expired. Please restart booking."}), 400

    data = pending["data"]
    pnr = _generate_pnr()
    booking = {
        "pnr": pnr,
        "train": data["train"],
        "from": data["from"],
        "to": data["to"],
        "journey_date": data["date"],
        "class": data["class"],
        "quota": QUOTAS.get(data["quota"], data["quota"]),
        "passengers": data["passengers"],
        "fare": data["fare"],
        "payment_method": data["payment_method"],
    }
    if data.get("upi_id"):
        booking["upi_id"] = data["upi_id"]

    user = _get_user(session["user"])
    if user:
        _store_booking(int(user["id"]), pnr, booking)
        subject = "RailSmart Booking Confirmation"
        body = json.dumps(booking, indent=2)
        _log_email(int(user["id"]), user["email"], subject, body)

    session.pop("chat_state", None)
    session.pop("pending_booking", None)

    reply = (
        f"Booking confirmed! PNR: {pnr}\n"
        f"Train: {booking['train']['number']} {booking['train']['name']}\n"
        f"From: {booking['from']}  To: {booking['to']}  Date: {booking['journey_date']}\n"
        f"Class: {booking['class']}  Quota: {booking['quota']}\n"
        f"Passengers: {len(booking['passengers'])}\n"
        f"Payment: {booking['payment_method']} (SUCCESS)\n"
        f"Confirmation sent to {user['email']}"
    )
    return jsonify({"reply": reply})


@app.route("/api/stations")
def station_search():
    query = request.args.get("q", "").strip().upper()
    results = []
    if not query:
        return jsonify(results)
    for code, name in STATIONS.items():
        if code.startswith(query) or query in name.upper():
            results.append({"code": code, "name": name})
            if len(results) >= 20:
                break
    return jsonify(results)


@app.route("/ticket/<pnr>/pdf")
def ticket_pdf(pnr: str):
    if "user" not in session:
        return redirect(url_for("login"))
    booking = _get_booking_by_pnr(session["user"], pnr)
    if not booking:
        return redirect(url_for("chat"))
    pdf_bytes = _build_ticket_pdf(booking, session["user"])
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{pnr}.pdf",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=False, port=port)
