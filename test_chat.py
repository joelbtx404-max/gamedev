#!/usr/bin/env python3
"""Test script for the PokéAPI chat functionality."""

import os
from dotenv import load_dotenv
from retroarch_capture import build_chat_agent, process_chat_message

def main():
    load_dotenv()
    
    # Create chat agent
    model = os.getenv("MODEL", "gpt-4o")
    chat_agent = build_chat_agent(model)
    
    # Test messages
    test_messages = [
        "What gender is Charizard?",
        "What are Pikachu's abilities?",
        "What moves can learn Thunderbolt?",
        "What type is effective against Water?"
    ]
    
    print("Testing PokéAPI Chat Agent")
    print("=" * 50)
    
    for message in test_messages:
        print(f"\nQuestion: {message}")
        try:
            response = process_chat_message(chat_agent, message)
            print(f"Answer: {response}")
        except Exception as e:
            print(f"Error: {e}")
        print("-" * 50)

if __name__ == "__main__":
    main()
