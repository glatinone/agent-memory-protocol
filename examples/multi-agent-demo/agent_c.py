"""Agent C — Marketing Agent example demonstrating AMP access control."""

import requests


class MarketingAgent:
    """Agent C - Marketing Agent that attempts to query user preferences."""

    def __init__(self, base_url: str = "http://localhost:8765"):
        self.base_url = base_url

    def try_access(self, user_id: str) -> list:
        """Query the AMP server for memories about the user.

        Args:
            user_id: The ID of the user whose memories to retrieve.

        Returns:
            A list of retrieved memory cells (or an empty list).
        """
        url = f"{self.base_url}/amp/v1/memories/search"
        headers = {
            "X-AMP-Agent-ID": "agent_marketing",
            "Content-Type": "application/json",
        }
        payload = {
            "query": "preference",
            "owner_id": user_id,
        }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])


if __name__ == "__main__":
    agent = MarketingAgent()
    try:
        results = agent.try_access("user_123")
        if len(results) == 0:
            print("Agent C retrieved 0 memories — access control working correctly")
        else:
            print("Error: Agent C retrieved memories it shouldn't have access to!")
    except Exception as e:
        print(f"Error connecting to AMP server: {e}")
