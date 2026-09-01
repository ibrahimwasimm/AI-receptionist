"""
test_messaging.py — Interactive Test Terminal for Dental AI Receptionist
=======================================================================
Test your WhatsApp receptionist directly in the terminal before or during launch!
"""

import sys
import io

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent import handle_message, CONVERSATION_HISTORY

def main():
    print("=" * 60)
    print("🦷 DENTAL CLINIC AI RECEPTIONIST — MESSAGING TEST CONSOLE")
    print("=" * 60)
    print("Type your message below (English, Roman Urdu, or Urdu).")
    print("Commands:")
    print("  'reset' -> Clear conversation history")
    print("  'exit'  -> Quit the console")
    print("=" * 60)

    test_phone = "923000000001"
    test_patient_name = "Test Patient"

    while True:
        try:
            user_input = input("\n[Patient] > ").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                print("\nExiting messaging test console. Goodbye!")
                break

            if user_input.lower() == "reset":
                CONVERSATION_HISTORY.pop(test_phone, None)
                print("[System] Conversation history cleared.")
                continue

            print("Thinking...", end="\r")
            reply = handle_message(test_phone, user_input, test_patient_name)
            print(f"[Sana (AI Receptionist)]:\n{reply}\n")

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n[Error]: {e}")

if __name__ == "__main__":
    main()
