import sys
import requests
from agent_a import CustomerServiceAgent
from agent_b import BillingAgent
from agent_c import MarketingAgent

def check_server(url="http://localhost:8765/amp/v1/health") -> bool:
    try:
        response = requests.get(url, timeout=3)
        return response.status_code == 200
    except Exception:
        return False

def main():
    if not check_server():
        print("Error: AMP server is not running on http://localhost:8765")
        print("Please start the server first using:")
        print("  uvicorn amp_server.main:app --host 127.0.0.1 --port 8765 (from server directory)")
        sys.exit(1)

    user_id = "user_123"
    message = "User prefers email correspondence."

    # --- AGENT A ---
    print("\n[AGENT A]")
    agent_a = CustomerServiceAgent()
    try:
        mem_id = agent_a.handle_conversation(user_id, message)
        print(f"CustomerServiceAgent received: '{message}'")
        print(f"Stored preference memory ID: {mem_id}")
    except Exception as e:
        print(f"Agent A encountered an error: {e}")
        sys.exit(1)

    # --- AGENT B ---
    print("\n[AGENT B]")
    agent_b = BillingAgent()
    try:
        # Search for preference memories and respond contextually
        response = agent_b.assist_user(user_id, "preference")
        print(f"BillingAgent assisted user: {user_id}")
        print(f"Retrieved response: \"{response}\"")
    except Exception as e:
        print(f"Agent B encountered an error: {e}")
        sys.exit(1)

    # --- AGENT C ---
    print("\n[AGENT C]")
    agent_c = MarketingAgent()
    try:
        results = agent_c.try_access(user_id)
        print(f"MarketingAgent try_access results: {len(results)} memories retrieved")
        if len(results) == 0:
            print("Agent C retrieved 0 memories — access control working correctly")
        else:
            print("WARNING: Agent C bypassed access control!")
    except Exception as e:
        print(f"Agent C encountered an error: {e}")
        sys.exit(1)

    # --- SUMMARY ---
    print("\n[SUMMARY]")
    print("AMP Demo complete. Two agents shared memory. One was blocked.")

if __name__ == "__main__":
    main()
