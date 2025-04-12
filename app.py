from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, auth, firestore
import requests
import os
from dotenv import load_dotenv
from flask_cors import CORS

# Load .env variables
load_dotenv()

# Get API Key
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")

# Service account dictionary
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
            "name": name
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


if __name__ == '__main__':
    print("Running server")
    app.run(debug=True)
