#imports
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import json
import os
from dotenv import load_dotenv
from flask import send_file   # 👈 add send_file

load_dotenv()

API_KEY = os.getenv("API_KEY")
load_dotenv()
# database update function

def update_user(cursor, userid, ai_data):
    fields = []
    values = []

    for key in ["budget", "location", "bhk", "intent", "phone", "email"]:
        value = ai_data.get(key)

        # only update if value exists and is not empty
        if value:
            # DB column name mismatch fix
            column = "locate" if key == "location" else key

            fields.append(f"{column} = %s")
            values.append(value)

    # nothing to update
    if not fields:
        return

    values.append(userid)

    query = f"""
        UPDATE users
        SET {", ".join(fields)}
        WHERE userid = %s
    """

    cursor.execute(query, values)
#flask server
app = Flask(__name__)
CORS(app)

# 🔴 ADD THIS HERE
@app.route("/chatbot.js")
def serve_js():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "chatbot.js")
    print("SERVING:", file_path)  # debug
    return send_file(file_path, mimetype="application/javascript")
print(app.url_map)
print("CWD:", os.getcwd())
print("FILES:", os.listdir())
@app.route('/chat', methods=['POST'])

def chat():
    #database
    conn = psycopg2.connect(
        dbname="chatbotdb",
        user="postgres",
        password="NFSMW@#2319",
        host="localhost",
        port="12000"
        )
    cursor = conn.cursor()
    #tepm testing
    print("API KEY:", API_KEY)
    #unpacking json
    data = request.json
    messages = data['messages']
    api_key = data['api_key']
    session_id = data['session_id']

    user_message = messages[-1]['content']
    
    print(f"Client: {api_key}")
    print(f"Session: {session_id}")
    print(f"Message: {user_message}")
    
    cursor.execute("""
    INSERT INTO users (userid, client)
    VALUES (%s, %s)
    ON CONFLICT (userid) DO NOTHING
    """, (session_id, api_key))
    conn.commit()

    #chatbot implementation
    MODEL = "openai/gpt-oss-120b"
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
    HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


    def get_ai_reply(messages):
        data = {
            "model": MODEL,
            "messages": [
            {"role": "system", "content": "You are a real estate assistant. Ask short questions to collect budget, location, and BHK."}
        ] + messages
        }
        try:

            response = requests.post(ENDPOINT, headers=HEADERS, json=data)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                return f"Groq API error: {response.status_code} | {response.text}"
        except Exception as e:
            return f"Error: {str(e)}"
    def get_structured_queries(messages):
        data = {
            "model": MODEL,
            "messages": [
            {
                "role": "system",
                "content": """You are a data extraction engine.

You MUST return ONLY valid JSON.
NO questions.
NO explanations.
NO extra text.

If information is missing, return empty strings.

Strict format:
{
  "budget": "",
  "location": "",
  "bhk": "",
  "intent": "buy/rent/unknown",
  "phone": "",
  "email": ""
}

bhk must be a single number like 1,2,3,4,5.
budget must be numeric like 50000.

Output JSON ONLY.
"""
            }
        ] + messages}
        try:
            response = requests.post(ENDPOINT, headers=HEADERS, json=data)

            if response.status_code != 200:
                print("EXTRACT API ERROR:", response.text)
                return "{}"

            content = response.json()["choices"][0]["message"]["content"]

            content = content.strip().replace("```json", "").replace("```", "")

            return content

        except Exception as e:
            print("EXTRACT EXCEPTION:", str(e))
            return "{}"

    def clean_ai_data(ai_data):
    # budget → extract number
        budget = ai_data.get("budget", "")
        budget = ''.join(filter(str.isdigit, budget))

    # bhk → only allow 1–5
        bhk = ai_data.get("bhk", "")
        bhk = ''.join(filter(str.isdigit, bhk))

        if bhk not in ["1", "2", "3", "4", "5"]:
            bhk = None

    # normalize intent
        intent = ai_data.get("intent", "").lower()
        if intent not in ["buy", "rent"]:
            intent = "unknown"

        return {
            "budget": budget,
            "location": ai_data.get("location"),
            "bhk": bhk,
            "intent": intent,
            "phone": ai_data.get("phone"),
            "email": ai_data.get("email")
    }

    clean_messages = [
    {
        "role": str(m.get("role", "user")),
        "content": str(m.get("content", ""))
    }
    for m in messages
    ]
    print("MESSAGES SENT TO AI:", clean_messages)
    ai_reply = get_ai_reply(clean_messages)
    print(f"Bot: {ai_reply}\n")

    ai_extract = get_structured_queries(clean_messages)

    # 1. Parse ONCE
    try:
        ai_data = json.loads(ai_extract) if ai_extract else {}
    except:
        print("❌ BAD JSON:", ai_extract)
        ai_data = {}

    # 2. Debug raw 
    print("\n====================")
    print("RAW AI EXTRACT:", ai_extract)
    print("====================\n")

    # 3. Clean ONCE
    ai_data = clean_ai_data(ai_data)

    # 4. Debug final (THIS is what goes to DB)
    print("FINAL VALUES:")
    print("budget:", ai_data.get("budget"))
    print("location:", ai_data.get("location"))
    print("bhk:", ai_data.get("bhk"))
    print("intent:", ai_data.get("intent"))
    print("phone:", ai_data.get("phone"))
    print("email:", ai_data.get("email"))
    
    update_user(cursor ,session_id, ai_data)
    conn.commit()

    return jsonify({"reply": ai_reply}) 
if __name__ == "__main__":
    # Render provides a PORT environment variable automatically
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

