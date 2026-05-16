import os
import json
import requests
import psycopg
import resend

from urllib.parse import urlparse

from flask import Flask, request, jsonify
from flask_cors import CORS

from flask_mail import Mail, Message


# ── APP ─────────────────────────────────
app = Flask(__name__)
CORS(app)


# ── EMAIL SETUP ─────────────────────────
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")

mail = Mail(app)


# ── ENV VARIABLES ──────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

resend.api_key = RESEND_API_KEY

# ── DATABASE CONNECTION ────────────────
def get_conn():
    return psycopg.connect(
        DATABASE_URL,
        sslmode="require",
        prepare_threshold=None
    )


# ── GROQ CONFIG ────────────────────────
MODEL = "llama-3.3-70b-versatile"

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}


# ── AI FUNCTION ────────────────────────
def get_ai_response_and_data(messages):

    system_prompt = """
You are a smart real estate sales assistant.

Your job is to naturally talk to the user and collect these details:

- intent
- location
- budget
- bhk
- special_preferences
- phone

IMPORTANT RULES:

1. Talk naturally like a real human sales assistant.
2. Keep replies short and conversational.
3. Stay focused on real estate only.
4. Gradually collect all important details.
5. Ask for phone number only after other details are collected.
6. Return ONLY valid JSON.

FORMAT:

{
  "reply": "your reply here",
  "extracted": {
    "intent": "",
    "location": "",
    "budget": "",
    "bhk": "",
    "special_preferences": "",
    "phone": ""
  }
}
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            }
        ] + messages,
        "response_format": {"type": "json_object"}
    }

    try:

        res = requests.post(
            ENDPOINT,
            headers=HEADERS,
            json=payload
        )

        print("GROQ STATUS:", res.status_code)

        if res.status_code != 200:
            print("GROQ ERROR:", res.text)
            return None

        content = res.json()["choices"][0]["message"]["content"]

        print("RAW AI:", content)

        return json.loads(content)

    except Exception as e:

        print("AI ERROR:", str(e))
        return None


# ── CLEAN NUMBERS ──────────────────────
def clean_number(val):

    if not val:
        return None

    digits = ''.join(filter(str.isdigit, str(val)))

    return digits if digits else None


# ── VERIFY CLIENT ──────────────────────
def verify_client(client_url, api_key):

    try:

        with get_conn() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        client_has_paid,
                        client_name,
                        client_email
                    FROM clients
                    WHERE
                        client_website_url = %s
                        AND client_api_key = %s
                """, (
                    client_url,
                    api_key
                ))

                result = cur.fetchone()

                if not result:

                    return {
                        "valid": False,
                        "paid": False
                    }

                has_paid = result[0]
                client_name = result[1]
                client_email = result[2]

                return {
                    "valid": True,
                    "paid": has_paid,
                    "client_name": client_name,
                    "client_email": client_email
                }

    except Exception as e:

        print("VERIFY CLIENT ERROR:", str(e))

        return {
            "valid": False,
            "paid": False
        }


# ── EMAIL DATA FETCH ───────────────────
def email_creator(session_id):

    try:

        with get_conn() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        phoneno,
                        location,
                        budget,
                        bhk,
                        special_preferences,
                        intent
                    FROM leads
                    WHERE session_id = %s
                """, (session_id,))

                result = cur.fetchone()

                if not result:
                    return None

                return {
                    "phoneno": result[0],
                    "location": result[1],
                    "budget": result[2],
                    "bhk": result[3],
                    "special_preferences": result[4],
                    "intent": result[5]
                }

    except Exception as e:

        print("EMAIL CREATOR ERROR:", str(e))
        return None

# ── SEND EMAIL(directly) ─────────────────────────

def send_lead_email(client_email, lead_data):

    try:

        resend.Emails.send({

            "from": "onboarding@resend.dev",

            "to": client_email,

            "subject": "🔥 New Real Estate Lead",

            "html": f"""

            <h2>🔥 New Lead Received</h2>

            <p><b>Intent:</b> {lead_data.get('intent')}</p>

            <p><b>Phone:</b> {lead_data.get('phoneno')}</p>

            <p><b>Budget:</b> {lead_data.get('budget')}</p>

            <p><b>Location:</b> {lead_data.get('location')}</p>

            <p><b>BHK:</b> {lead_data.get('bhk')}</p>

            <p><b>Special Preferences:</b> {lead_data.get('special_preferences')}</p>

            """
        })

        print("✅ EMAIL SENT")

    except Exception as e:

        print("RESEND ERROR:", str(e))

# ── SEND EMAIL(directly) ─────────────────────────(temporarily shut down, using resend instead)
"""
def send_lead_email(client_email, lead_data):

    try:

        msg = Message(
            subject="🔥 New Real Estate Lead",
            sender=app.config['MAIL_USERNAME'],
            recipients=[client_email]
        )

        msg.body = f"""""""
🔥 New Lead Received

Intent: {lead_data.get('intent')}
Phone: {lead_data.get('phoneno')}
Budget: {lead_data.get('budget')}
Location: {lead_data.get('location')}
BHK: {lead_data.get('bhk')}

Special Preferences:
{lead_data.get('special_preferences')}
""""""

        mail.send(msg)

        print("✅ EMAIL SENT")

    except Exception as e:

        print("EMAIL ERROR:", str(e))
"""

# ── CHAT ROUTE ─────────────────────────
@app.route("/chat", methods=["POST"])
def chat():

    try:

        req = request.json

        api_key = req.get("api_key")
        session_id = req.get("session_id")

        client_url = request.headers.get("Origin")

        if not client_url:
            client_url = request.headers.get("Referer")

        parsed = urlparse(client_url)

        client_url = f"{parsed.scheme}://{parsed.netloc}"

        print("client_url:", client_url)
        print("api_key:", api_key)
        print("session id", session_id)
        client_data = verify_client(client_url, api_key)

        if not client_data["valid"]:

            return jsonify({
                "reply": "Invalid client."
            })

        if not client_data["paid"]:

            return jsonify({
                "reply": "Service inactive."
            })

        client_name = client_data["client_name"]
        client_email = client_data["client_email"]

        messages = req.get("messages", [])

        result = get_ai_response_and_data(messages)

        if not result:

            return jsonify({
                "reply": "AI temporarily unavailable."
            })

        ai_reply = result.get("reply", "Hello")

        ext = result.get("extracted", {})

        print("EXTRACTED:", ext)

        phone = clean_number(ext.get("phone"))
        bhk = clean_number(ext.get("bhk"))
        budget = clean_number(ext.get("budget"))

        location = ext.get("location")
        special_preferences = ext.get("special_preferences")
        intent = ext.get("intent")

        # ── STORE LEAD ──────────────────
        if phone:

            try:

                with get_conn() as conn:

                    with conn.cursor() as cur:

                        cur.execute("""
                            INSERT INTO leads
                            (
                                phoneno,
                                location,
                                budget,
                                bhk,
                                special_preferences,
                                client_name,
                                intent,
                                session_id,
                                client_api_key
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            phone,
                            location,
                            int(budget) if budget else None,
                            int(bhk) if bhk else None,
                            special_preferences,
                            client_name,
                            intent,
                            session_id,
                            api_key
                        ))

                print("✅ LEAD STORED")

                lead_data = email_creator(session_id)

                if lead_data:
                    send_lead_email(client_email, lead_data)
                    send_lead_email("n21816012@gmail.com", lead_data)

            except Exception as e:

                print("DB ERROR:", str(e))

        return jsonify({
            "reply": ai_reply
        })

    except Exception as e:

        print("SERVER ERROR:", str(e))

        return jsonify({
            "reply": "Server error"
        }), 500


# ── HEALTH CHECK ───────────────────────
@app.route("/")
def home():
    return "Server running"


# ── START SERVER ───────────────────────
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
