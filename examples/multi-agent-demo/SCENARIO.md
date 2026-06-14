# AMP Multi-Agent Demo Scenario

This demo showcases the Agent Memory Protocol (AMP) by showing how different agents from different frameworks can share memory under specific access controls.

## The Story

1. **Agent A (Customer Service Agent)**:
   - Interacts with a customer (e.g. `user_123`) and extracts their preference: *"User prefers email correspondence."*
   - Stores this memory into the AMP server.
   - Restricts read permissions so that only billing agents can read it (`readable_by = ["agent_billing_*"]`).

2. **Agent B (Billing Agent)**:
   - Needs to process a bill or query for `user_123`.
   - Queries the AMP server for the user's memories using their own agent identifier (`agent_billing_v1`).
   - Retrieves the email preference stored by Agent A because `agent_billing_v1` matches the policy pattern `agent_billing_*`.
   - Responds contextually: *"I see you prefer email, so I will send your bill there."*

3. **Agent C (Marketing Agent)**:
   - Wants to target `user_123` with a marketing campaign.
   - Queries the AMP server for memories about `user_123` using their agent identifier (`agent_marketing`).
   - Retrieves **0 results** because `agent_marketing` does not match the access policy `agent_billing_*`.
   - Access control prevents the marketing agent from retrieving this data.
