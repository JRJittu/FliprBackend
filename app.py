from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, auth, firestore
import requests
import os
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime
from openai import OpenAI

load_dotenv()  
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")

firebase_creds = {
    "type": os.getenv("GCP_TYPE"),
    "project_id": os.getenv("GCP_PROJECT_ID"),
    "private_key_id": os.getenv("GCP_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GCP_PRIVATE_KEY").encode('utf-8').decode('unicode_escape'),
    "client_email": os.getenv("GCP_CLIENT_EMAIL"),
    "client_id": os.getenv("GCP_CLIENT_ID"),
    "auth_uri": os.getenv("GCP_AUTH_URI"),
    "token_uri": os.getenv("GCP_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GCP_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("GCP_CLIENT_CERT_URL"),
}

# Initialize Firebase Admin
cred = credentials.Certificate(firebase_creds)
firebase_admin.initialize_app(cred)
db = firestore.client()
print("Connected to Firestore")

app = Flask(__name__)
CORS(app)

# Set up OpenAI Groq client
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

# Chat history initialized with system prompt
chat_history = [
    {
        "role": "system",
        "content": """
You are a financial assistant. For each user message, extract the following structured data:
- amount
- category (only if it's expenditure, choose from: food, entertainment, shopping, travel, bills, daily utilities)
- description
- type: income or expenditure
- source (only if it's income, otherwise null)

Return the data in this exact JSON format, dont give any messages along with that and dont miss any semicolon, brackets etc:
{
  "amount": "<amount>",
  "category": "<category or null>",
  "description": "<description>",
  "type": "<income or expenditure>",
  "source": "<source or null>"
}
"""
    }
]


@app.route('/user/register', methods=['POST'])
def register():
    try:
        data = request.json
        email = data['email']
        password = data['password']
        name = data.get('name', '')

        # Create user with Firebase Auth
        user = auth.create_user(email=email, password=password, display_name=name)

        # Store additional user data in Firestore
        db.collection("users").document(user.uid).set({
            "email": email,
            "name": name,
            "balance": 10000,
        })

        return jsonify({"message": "User registered", "uid": user.uid}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/user/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data['email']
        password = data['password']

        # Firebase REST API call for login
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }

        res = requests.post(url, json=payload)
        res_data = res.json()

        if "idToken" in res_data:
            user = auth.get_user(res_data["localId"])
            return jsonify({
                "message": "Login successful",
                "idToken": res_data["idToken"],
                "refreshToken": res_data["refreshToken"],
                "expiresIn": res_data["expiresIn"],
                "uid": user.uid,
                "email": user.email,
                "name": user.display_name,
            }), 200
        else:
            return jsonify({"error": res_data.get("error", {}).get("message", "Login failed")}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/user/<uid>/add-goal', methods=['POST'])
def add_goal(uid):
    try:
        print("called add goal")
        data = request.json
        goal_name = data['goal_name']
        description = data['description']
        target_amount = data['target_amount']
        created_date = datetime.utcnow().isoformat()   # current UTC date

        # Goal dictionary
        goal_data = {
            "goal_name": goal_name,
            "target_amount": target_amount,
            "description": description,
            "current_saving": 0,
            "completed": False,
            "created_date": created_date,
            "difficulty": "medium",
            "deadline_date": None
        }

        # Save to Firestore under subcollection
        db.collection("users").document(uid).collection("goals").add(goal_data)

        return jsonify({"message": "Goal added successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/user/<uid>/add-expense', methods=['POST'])
def add_expense(uid):
    try:
        data = request.json
        record_type = data['type']  # 'income' or 'expenditure'
        entry = data['entry']       # dictionary like {amount: 100, reason: "...", category: "..."}

        amount = float(entry['amount'])
        now = datetime.utcnow()
        key = f"{now.month:02d}-{now.year}_{record_type}"  # e.g., 04-2025_income

        # Reference to user document
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404

        user_data = user_doc.to_dict()
        balance = user_data.get("balance", 0)

        # Update balance
        if record_type == "expenditure":
            balance -= amount
        elif record_type == "income":
            balance += amount

        # Update monthly entry
        existing_data = user_data.get(key, [])
        updated_data = existing_data + [entry]

        # Save updates to Firestore
        user_ref.update({
            key: updated_data,
            "balance": balance
        })

        return jsonify({"message": f"{record_type.capitalize()} added to {key}", "updated_balance": balance}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400



@app.route('/user/<uid>', methods=['GET'])
def get_user(uid):
    try:
        doc = db.collection("users").document(uid).get()
        if doc.exists:
            return jsonify(doc.to_dict()), 200
        else:
            return jsonify({"error": "User not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/user/<uid>/goals', methods=['GET'])
def get_goals(uid):
    try:
        goals_ref = db.collection("users").document(uid).collection("goals").stream()
        goals = [{**doc.to_dict(), "id": doc.id} for doc in goals_ref]
        return jsonify(goals), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/user/<uid>/goals/<goal_name>', methods=['GET'])
def get_specific_goal(uid, goal_name):
    try:
        goals_ref = db.collection("users").document(uid).collection("goals")
        query = goals_ref.where("goal_name", "==", goal_name).stream()
        goal_list = [doc.to_dict() for doc in query]
        
        if not goal_list:
            return jsonify({"error": "Goal not found"}), 404

        return jsonify(goal_list[0]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/gpt/expense-details", methods=["POST"])
def gpt_expenseDetails():
    user_message = request.json.get("message")

    # Add user message to the chat history
    chat_history.append({"role": "user", "content": user_message})

    # Generate model response using Groq
    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=chat_history
    )

    assistant_reply = response.choices[0].message.content

    # Add assistant's reply to chat history
    chat_history.append({"role": "assistant", "content": assistant_reply})
    # Return the reply
    return jsonify({"reply": assistant_reply})


@app.route('/user/<uid>/balance', methods=['GET'])
def get_balance(uid):
    try:
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404
        balance = user_doc.to_dict().get("balance", 0)
        return jsonify({"balance": balance}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/top-goal/<uid>', methods=['GET'])
def get_sorted_user_goals(uid):
    try:
        goals_ref = db.collection("users").document(uid).collection("goals").stream()
        user_goals = [doc.to_dict() for doc in goals_ref]

        # Filter only uncompleted goals
        uncompleted_goals = [g for g in user_goals if not g.get("completed", False)]

        # Sort by difficulty (hard > medium > easy), then by target_amount descending
        difficulty_order = {"hard": 0, "medium": 1, "easy": 2}
        uncompleted_goals.sort(
            key=lambda g: (
                difficulty_order.get(g.get("difficulty", "medium"), 1),
                -float(g.get("target_amount", 0))  # Safely cast to float
            )
        )

        # Return only the top goal, if available
        if uncompleted_goals:
            return jsonify(uncompleted_goals[0]), 200
        else:
            return jsonify({"message": "No uncompleted goals found"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


chat_history2 = [
    {
        "role": "system",
        "content": "You are a helpful financial budgeting assistant. Keep your answers short, clear, and to the point—preferably 1–2 sentences."
    }
]

@app.route("/gpt/chat", methods=["POST"])
def gpt_chat():
    user_message = request.json.get("message")
    
    chat_history2.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=chat_history2
    )

    assistant_reply = response.choices[0].message.content

    chat_history2.append({"role": "assistant", "content": assistant_reply})

    return jsonify({"reply": assistant_reply})


@app.route('/user/<uid>/transactions', methods=['GET'])
def get_user_transactions(uid):
    try:
        trans_type = request.args.get('type')  # "income" or "expenditure"
        month_year = request.args.get('month_year')  # e.g. "04-2025"

        if trans_type not in ['income', 'expenditure']:
            return jsonify({'error': 'Invalid type. Must be "income" or "expenditure".'}), 400
        if not month_year:
            return jsonify({'error': 'month_year parameter is required (e.g., 04-2025).'}), 400

        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404

        user_data = user_doc.to_dict()
        key = f"{month_year}_{trans_type}"
        transactions = user_data.get(key, [])

        return jsonify(transactions), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 400



if __name__ == '__main__':
    print("Running server")
    app.run(debug=True)
