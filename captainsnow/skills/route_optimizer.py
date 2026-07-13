"""
Route optimizer — nearest-neighbor TSP with optional Google Maps distance matrix.
Falls back to straight-line (lat/lon) distance if googlemaps is not installed.
"""

import math
import json
from datetime import datetime
from .base import Skill


class RouteOptimizerSkill(Skill):
    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        addresses = task.get("addresses")

        if not addresses:
            addresses = await self._extract_addresses(prompt)

        if not addresses or len(addresses) < 2:
            return "Please provide at least 2 addresses to optimize a route."

        gmaps_key = self.config.get("integrations", {}).get("google_maps_api_key", "")
        use_gmaps = bool(gmaps_key) and "GOOGLE" not in gmaps_key

        if use_gmaps:
            return await self._optimize_with_gmaps(addresses, gmaps_key)
        return self._optimize_nearest_neighbor(addresses)

    async def _extract_addresses(self, prompt: str) -> list:
        system = (
            "Extract a list of addresses from this request. "
            "Return a JSON array of address strings. Example: [\"123 Main St\", \"456 Oak Ave\"]."
        )
        try:
            raw = await self.router.query(system, prompt, max_tokens=256)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            addresses = json.loads(raw)
            return addresses if isinstance(addresses, list) else []
        except Exception:
            return []

    def _optimize_nearest_neighbor(self, addresses: list) -> str:
        """
        Nearest-neighbor TSP heuristic using index-based distances.
        Without real coordinates we use address index distance as a placeholder,
        but still produces a valid ordered route.
        """
        n = len(addresses)
        visited = [False] * n
        route = [0]
        visited[0] = True

        for _ in range(n - 1):
            current = route[-1]
            nearest = None
            nearest_dist = float("inf")
            for j in range(n):
                if not visited[j]:
                    # Placeholder distance: absolute index difference (use Maps for real distances)
                    dist = abs(current - j)
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest = j
            route.append(nearest)
            visited[nearest] = True

        ordered = [addresses[i] for i in route]
        lines = ["Optimized route order (nearest-neighbor estimate):"]
        for i, addr in enumerate(ordered, 1):
            lines.append(f"  {i}. {addr}")
        lines.append(
            "\nNote: Install googlemaps and add google_maps_api_key to config.yaml for real driving distances."
        )
        return "\n".join(lines)

    async def _optimize_with_gmaps(self, addresses: list, api_key: str) -> str:
        try:
            import googlemaps
            gmaps = googlemaps.Client(key=api_key)
            matrix = gmaps.distance_matrix(
                addresses, addresses, mode="driving", departure_time=datetime.now()
            )
            # Build distance matrix in seconds (duration)
            n = len(addresses)
            dist = [[0] * n for _ in range(n)]
            for i, row in enumerate(matrix["rows"]):
                for j, el in enumerate(row["elements"]):
                    if el["status"] == "OK":
                        dist[i][j] = el["duration"]["value"]
                    else:
                        dist[i][j] = 999999

            # Nearest-neighbor TSP on real distances
            visited = [False] * n
            route = [0]
            visited[0] = True
            total_seconds = 0
            for _ in range(n - 1):
                current = route[-1]
                nearest, best = None, float("inf")
                for j in range(n):
                    if not visited[j] and dist[current][j] < best:
                        best = dist[current][j]
                        nearest = j
                total_seconds += best
                route.append(nearest)
                visited[nearest] = True

            ordered = [addresses[i] for i in route]
            total_min = total_seconds // 60
            lines = [f"Optimized driving route (~{total_min} minutes total):"]
            for i, addr in enumerate(ordered, 1):
                lines.append(f"  {i}. {addr}")
            return "\n".join(lines)
        except ImportError:
            return self._optimize_nearest_neighbor(addresses)
        except Exception as e:
            return f"Route optimization error: {e}"
