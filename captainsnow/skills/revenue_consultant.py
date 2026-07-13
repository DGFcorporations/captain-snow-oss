from .base import Skill


class RevenueConsultantSkill(Skill):
    """Pulls real Stripe + Supabase data and generates a revenue analysis."""

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "Give me a revenue overview.")
        stripe_data = await self._get_stripe_summary()
        supabase_data = await self._get_supabase_summary()
        analysis_prompt = (
            f"Financial snapshot:\n{stripe_data}\n{supabase_data}\n\n"
            f"User request: {prompt}\n\n"
            "Provide a concise revenue analysis with key insights and any recommended actions."
        )
        return await self.router.query(
            "You are a revenue strategist. Be direct and data-driven.",
            analysis_prompt,
            max_tokens=512,
        )

    async def _get_stripe_summary(self) -> str:
        stripe_key = self.config.get("integrations", {}).get("stripe", {}).get("api_key", "")
        if not stripe_key or "STRIPE" in stripe_key:
            return "Stripe: not configured."
        try:
            import stripe
            stripe.api_key = stripe_key
            balance = stripe.Balance.retrieve()
            available = sum(b.amount for b in balance.available) / 100
            pending = sum(b.amount for b in balance.pending) / 100
            charges = stripe.Charge.list(limit=10)
            recent_total = sum(c.amount for c in charges.data if c.paid) / 100
            customer_count = stripe.Customer.list(limit=1).get("total_count", "?")
            return (
                f"Stripe — Balance: ${available:.2f} available, ${pending:.2f} pending | "
                f"Last 10 charges: ${recent_total:.2f} | Customers: {customer_count}"
            )
        except Exception as e:
            return f"Stripe: error — {e}"

    async def _get_supabase_summary(self) -> str:
        sb_cfg = self.config.get("integrations", {}).get("supabase", {})
        url = sb_cfg.get("url", "")
        key = sb_cfg.get("key", "")
        if not url or not key or "SUPABASE" in key:
            return "Supabase: not configured."
        try:
            from supabase import create_client
            client = create_client(url, key)
            result = client.table("customers").select("id", count="exact").execute()
            count = result.count if hasattr(result, "count") else len(result.data)
            return f"Supabase — Customers table: {count} records"
        except Exception as e:
            return f"Supabase: error — {e}"
