import os
import json
import requests
import psycopg
from urllib.parse import urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
from twilio.rest import Client

# ── APP ─────────────────────────────────
app = Flask(__name__)
CORS(app)

# ── ENV VARIABLES ──────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
account_sid = os.getenv("account_sid")
auth_token = os.getenv("auth_token")

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

- intent (buy, rent, commercial, office, etc)
- location
- budget
- bhk
- special_preferences
- phone

IMPORTANT RULES:

1. Talk naturally like a real human sales assistant.
2. Keep replies short and conversational.
3. Stay focused on real estate only.
4. If the user goes off-topic, politely bring them back to property discussion.
5. Gradually collect all important details.
6. DO NOT ask for phone number early.
7. Ask for phone number ONLY AFTER you already have:
   - intent
   - location
   - budget
   - bhk
8. After collecting all important details, ask for WhatsApp/phone number.
9. Once phone number is received, clearly say:
   "Perfect. Our team will contact you shortly on WhatsApp/phone."

10. If user already provides multiple details together, do not ask them again.
11. Extract data even if spelling mistakes exist.
12. Convert budgets like:
   - 2Cr -> 20000000
   - 75L -> 7500000
13. If a field is missing, keep it empty.
14. Return ONLY valid JSON.

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
    
def verify_client(client_url, api_key):

    try:

        with get_conn() as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        client_has_paid,
                        client_phone,
                        client_name
                    FROM clients
                    WHERE
                        client_website_url = %s
                        AND client_api_key = %s
                """, (
                    client_url,
                    api_key
                ))

                result = cur.fetchone()

                # no client found
                if not result:

                    return {
                        "valid": False,
                        "paid": False
                    }

                has_paid = result[0]      
                phoneno = result[1]
                client_name = result[2]
                return {
                    "valid": True,
                    "paid": has_paid,
                    "client_phone":phoneno,
                    "client_name":client_name
                }

    except Exception as e:

        print("VERIFY CLIENT ERROR:", str(e))

        return {
            "valid": False,
            "paid": False
        }
# ── CHAT ROUTE ─────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        req = request.json
        api_key = req.get("api_key")
        client_url = request.headers.get("Origin")
        if not client_url:
            client_url = request.headers.get("Referer")
        parsed = urlparse(client_url)
        client_url = f"{parsed.scheme}://{parsed.netloc}"
        print("client_url",client_url)
        print("api_key",api_key)
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
        messages = req.get("messages", [])

        print("MESSAGES:", messages)

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
                                intent
                            )

                            VALUES (%s,%s, %s, %s, %s,%s,%s)
                        """, (
                            phone,
                            location, 
                            int(budget) if budget else None,
                            int(bhk) if bhk else None,
                            special_preferences,
                            client_name,
                            intent
                        ))

                print("✅ LEAD STORED")
                client = Client(account_sid, auth_token)
                phoneno = client_data["client_phone"] or req.get("client_phone")
                message = client.messages.create(
                from_='whatsapp:+14155238886',
                body=f"""
                🔥 New Lead
                Intent: {intent}
                Phone: {phone}
                Location: {location}
                Budget: ₹{budget}
                BHK: {bhk}

                Preferences:
                {special_preferences}
                """,
                to=f'whatsapp:+91{phoneno}'
            )
                print("WHATSAPP SENT:", message.sid)
                print("phone no",phoneno)
            
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
