import requests

class CustomerServiceAgent:
    def __init__(self, base_url: str = "http://localhost:8765/amp/v1"):
        self.base_url = base_url.rstrip("/")

    def handle_conversation(self, user_id: str, message: str) -> str:
        url = f"{self.base_url}/memories"
        headers = {
            "X-AMP-Agent-ID": "agent_customer_service"
        }
        body = {
            "type": "semantic",
            "content": {
                "text": message,
                "metadata": {"topic": "preference"}
            },
            "identity": {
                "owner_id": user_id,
                "owner_type": "user"
            },
            "access_policy": {
                "readable_by": ["agent_billing_*"]
            }
        }
        response = requests.post(url, json=body, headers=headers)
        if response.status_code == 201:
            data = response.json()
            return data["id"]
        else:
            response.raise_for_status()

    def get_user_context(self, user_id: str) -> list:
        url = f"{self.base_url}/memories/search"
        headers = {
            "X-AMP-Agent-ID": "agent_customer_service"
        }
        body = {
            "query": "preference",
            "owner_id": user_id
        }
        response = requests.post(url, json=body, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])

if __name__ == "__main__":
    # Example standalone execution
    agent = CustomerServiceAgent()
    try:
        mem_id = agent.handle_conversation("user_123", "User prefers email correspondence.")
        print(f"Agent A stored memory: {mem_id}")
    except Exception as e:
        print(f"Error communicating with AMP server: {e}")
        print("Make sure the AMP server is running on http://localhost:8765")
