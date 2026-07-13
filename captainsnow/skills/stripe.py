import stripe
import json
from .base import Skill

class StripeSkill(Skill):
    async def execute(self, task: dict) -> str:
        action = task.get("action", "query_or_modify")
        prompt = task.get("prompt", "")
        
        api_key = self.config.get("integrations", {}).get("stripe", {}).get("api_key", "") or ""
        # Reject obviously-bad keys with a clear, actionable error instead of
        # letting the Stripe SDK return a confusing "Invalid API Key" message.
        if not api_key or "${" in api_key or api_key == "mock_key" or "mock" in api_key.lower():
            return (
                "Stripe is not configured. Set the STRIPE_API_KEY environment "
                "variable (value must start with sk_live_ or sk_test_), "
                "then restart."
            )
        if not api_key.startswith(("sk_live_", "sk_test_", "rk_live_", "rk_test_")):
            return (
                f"Stripe key looks wrong — it starts with '{api_key[:7]}…'. "
                "It must start with sk_live_, sk_test_, rk_live_, or rk_test_. "
                "If you pasted a publishable key (pk_...), swap it for the secret key."
            )
        stripe.api_key = api_key

        system = "You are a Stripe API expert helper. Translate this user query into a structured Stripe action: list customers, list charges, retrieve balance, or other. Reply in JSON: {\"action\": \"list_customers|list_charges|balance|unknown\"}."
        try:
            response = await self.router.query(system, prompt, complexity="simple")
            data = json.loads(response)
            action_type = data.get("action", "unknown")
        except Exception:
            action_type = "balance"
            
        if action_type == "list_customers":
            try:
                if api_key == "mock_key" or "mock" in api_key:
                    return "Stripe Customers (Simulated):\n- Customer 1: John Doe (john@example.com)\n- Customer 2: Jane Smith (jane@example.com)"
                customers = stripe.Customer.list(limit=5)
                return "Stripe Customers:\n" + "\n".join(f"- {c.name or 'No Name'} ({c.email})" for c in customers.data)
            except Exception as e:
                return f"Stripe error: {e}"
        elif action_type == "list_charges":
            try:
                if api_key == "mock_key" or "mock" in api_key:
                    return "Stripe Recent Charges (Simulated):\n- ch_1: $45.00 (Succeeded)\n- ch_2: $120.00 (Succeeded)"
                charges = stripe.Charge.list(limit=5)
                return "Stripe Charges:\n" + "\n".join(f"- {c.id}: ${c.amount/100:.2f} ({c.status})" for c in charges.data)
            except Exception as e:
                return f"Stripe error: {e}"
        else:
            try:
                if api_key == "mock_key" or "mock" in api_key:
                    return "Stripe Balance (Simulated):\nAvailable: $5,420.00 USD\nPending: $340.00 USD"
                balance = stripe.Balance.retrieve()
                avail = ", ".join(f"${b.amount/100:.2f} {b.currency.upper()}" for b in balance.available)
                pend = ", ".join(f"${b.amount/100:.2f} {b.currency.upper()}" for b in balance.pending)
                return f"Stripe Balance:\nAvailable: {avail}\nPending: {pend}"
            except Exception as e:
                return f"Stripe error: {e}"
