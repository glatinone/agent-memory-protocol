#!/usr/bin/env python
"""
Example demonstrating the LangChain integration with AMP (Agent Memory Protocol).
This file shows how to use AMPMemory to persist conversational history.
"""

import sys
import os
import datetime

# Add the parent directories to path so we can import amp_client
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from amp_client.exceptions import AMPError

class MockAMPClient:
    """Mock AMPClient storing memories in-memory for demonstration purposes."""
    def __init__(self, server_url: str = "http://localhost:8765", agent_id: str = "mock-agent"):
        self.server_url = server_url
        self.agent_id = agent_id
        self.db = []

    def remember(
        self,
        content: str,
        owner_id: str,
        type: str = "episodic",
        importance: float = 0.5,
        **kwargs
    ) -> dict:
        memory_id = f"mem_mock_{len(self.db) + 1}"
        cell = {
            "id": memory_id,
            "type": type,
            "content": {
                "text": content,
                "metadata": {}
            },
            "identity": {
                "owner_id": owner_id,
                "owner_type": "user",
                "created_by": self.agent_id
            },
            "lifecycle": {
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": "active"
            },
            "scoring": {
                "importance": importance
            }
        }
        self.db.append(cell)
        print(f"[Mock Server] Stored episodic memory: {memory_id} -> '{content}'")
        return cell

    def list_memories(self, owner_id=None, type=None, limit=20):
        results = []
        for cell in self.db:
            if owner_id and cell["identity"]["owner_id"] != owner_id:
                continue
            if type and cell["type"] != type:
                continue
            if cell["lifecycle"]["status"] != "active":
                continue
            results.append(cell)
        return results[:limit]

    def forget(self, memory_id):
        for cell in self.db:
            if cell["id"] == memory_id:
                cell["lifecycle"]["status"] = "deleted"
                print(f"[Mock Server] Forgot memory: {memory_id}")
                return

def run_simulation(memory_class, client):
    print("--- 1. Initializing AMPMemory ---")
    memory = memory_class(client=client, owner_id="user_john_doe", memory_key="chat_history")
    
    print("\n--- 2. Saving Context (Simulating user/AI turn) ---")
    memory.save_context({"input": "Hello! I am John, and I love Python programming."}, {"output": "Hi John! That's awesome. Python is great."})
    
    print("\n--- 3. Saving another context turn ---")
    memory.save_context({"input": "I also prefer dark mode in my IDEs."}, {"output": "Got it, dark mode is easier on the eyes."})

    print("\n--- 4. Loading Memory Variables ---")
    history = memory.load_memory_variables({})
    print("Loaded history variables:")
    print(history)

    print("\n--- 5. Clearing Memory ---")
    memory.clear()

    print("\n--- 6. Verifying Memory is cleared ---")
    history_after_clear = memory.load_memory_variables({})
    print("Loaded history variables (after clear):")
    print(history_after_clear)

def main():
    print("====================================================")
    print("AMP LangChain Integration Example")
    print("====================================================")

    # 1. Initialize our mock client for the demo
    client = MockAMPClient()
    
    # Optional: Swap with real AMPClient if server is running
    # from amp_client.client import AMPClient
    # client = AMPClient(server_url="http://localhost:8765", agent_id="langchain-agent")

    try:
        from langchain_core.memory import BaseMemory
        from amp_client.integrations.langchain import AMPMemory
        print("Successfully imported langchain-core! Running actual AMPMemory implementation.")
        run_simulation(AMPMemory, client)
    except ImportError:
        print("langchain-core not found. Running simulation with a mock implementation of BaseMemory.")
        
        # Define a mock BaseMemory mirroring AMPMemory to simulate behavior
        class MockBaseMemory:
            def __init__(self, client, owner_id, memory_key="history"):
                self.client = client
                self.owner_id = owner_id
                self.memory_key = memory_key

            def load_memory_variables(self, inputs):
                memories = self.client.list_memories(
                    owner_id=self.owner_id,
                    type="episodic",
                    limit=100
                )
                memories.sort(key=lambda x: x.get("lifecycle", {}).get("created_at", ""))
                history_str = "\n".join(mem.get("content", {}).get("text", "") for mem in memories)
                return {self.memory_key: history_str}

            def save_context(self, inputs, outputs):
                input_text = next(iter(inputs.values())) if inputs else ""
                output_text = next(iter(outputs.values())) if outputs else ""
                if input_text:
                    self.client.remember(f"Human: {input_text}", self.owner_id, "episodic")
                if output_text:
                    self.client.remember(f"AI: {output_text}", self.owner_id, "episodic")

            def clear(self):
                memories = self.client.list_memories(owner_id=self.owner_id, limit=1000)
                for mem in memories:
                    self.client.forget(mem["id"])

        run_simulation(MockBaseMemory, client)

if __name__ == "__main__":
    main()
