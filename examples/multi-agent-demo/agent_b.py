import requests

class BillingAgent:
    def assist_user(self, user_id: str, query: str) -> str:
        """
        Queries the AMP server for the user's memories using the billing agent identity.
        If any retrieved memory contains the keyword "email", returns a contextual response
        confirming email preference. Otherwise, returns a default fallback message.
        """
        url = "http://localhost:8765/amp/v1/memories/search"
        headers = {
            "X-AMP-Agent-ID": "agent_billing_v1",
            "Content-Type": "application/json"
        }
        payload = {
            "query": query,
            "owner_id": user_id
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                for memory in results:
                    content = memory.get("content", {})
                    text = content.get("text", "")
                    if "email" in text.lower():
                        return "I see you prefer email, so I will send your bill there."
        except Exception:
            # Fallback to the default response on any connection or request failure
            pass
            
        return "Could not find preferred communication method. Sending bill to default address."

if __name__ == "__main__":
    agent = BillingAgent()
    response = agent.assist_user("user_123", "preference")
    print(response)
