import os
import json
import requests
import psycopg

from flask import Flask, request, jsonify
from flask_cors import CORS

# ── APP ─────────────────────────────────
app = Flask(__name__)
CORS(app)

# ── ENV VARIABLES ──────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

print("GROQ KEY EXISTS:", bool(GROQ_API_KEY))
print("DATABASE URL EXISTS:", bool(DATABASE_URL))

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
You are a real estate assistant.

Your tasks:
1. Reply naturally and briefly.
2. Extract:
- budget
- location
- bhk
- phone

Return ONLY valid JSON.

Format:
{
  "reply": "your reply here",
  "extracted": {
    "budget": "",
    "location": "",
    "bhk": "",
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

# ── CHAT ROUTE ─────────────────────────
@app.route("/chat", methods=["POST"])
def chat():

    try:

        req = request.json

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

        # ── STORE LEAD ──────────────────
        if phone:

            try:

                with get_conn() as conn:

                    with conn.cursor() as cur:

                        cur.execute("""
                            INSERT INTO leads
                            (
                                client_name,
                                phoneno,
                                location,
                                budget,
                                bhk
                            )

                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            "unknown",
                            phone,
                            ext.get("location"),
                            int(budget) if budget else None,
                            int(bhk) if bhk else None
                        ))

                print("✅ LEAD STORED")

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
