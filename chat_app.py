#!/usr/bin/env python3
"""Simple Flask app for PokéAPI chat functionality."""

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from retroarch_capture import build_chat_agent, process_chat_message

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Create chat agent
model = os.getenv("MODEL", "gpt-4o")
chat_agent = build_chat_agent(model)

@app.route("/api/chat", methods=["POST"])
def chat_endpoint():
    """Handle chat messages and return PokéAPI responses."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        message = data.get("message", "")
        if not message:
            return jsonify({"error": "No message provided"}), 400
        
        # Process the message
        response = process_chat_message(chat_agent, message)
        
        return jsonify({
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": f"Chat error: {str(e)}"}), 500

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "pokemon-chat"})

if __name__ == "__main__":
    port = int(os.getenv("CHAT_PORT", "5052"))
    print(f"PokéAPI Chat service running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
