import atexit
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

import httpx

_test_database = tempfile.TemporaryDirectory()
os.environ["FUT7_DATABASE_URL"] = (
    f"sqlite:///{(Path(_test_database.name) / 'fut7-test.db').as_posix()}"
)

from web_app import app
from fut7.database import engine


def _cleanup_test_database() -> None:
    engine.dispose()
    _test_database.cleanup()


atexit.register(_cleanup_test_database)


class WebAppFlowTests(unittest.TestCase):
    def test_coach_player_match_and_result_flow(self):
        asyncio.run(self._run_coach_player_match_and_result_flow())

    async def _run_coach_player_match_and_result_flow(self) -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as coach:
                response = await coach.post(
                    "/api/auth/register/coach",
                    json={
                        "name": "Treinador Teste",
                        "email": "treinador@exemplo.com",
                        "password": "senha-segura-123",
                        "team_name": "Time de Teste",
                        "pin": "012345",
                    },
                )
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual((await coach.get("/")).status_code, 200)
                team_id = response.json()["user"]["team"]["id"]

                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as player:
                    response = await player.post(
                        "/api/auth/register/player",
                        json={
                            "name": "Atleta Teste",
                            "email": "atleta@exemplo.com",
                            "password": "senha-segura-456",
                            "team_id": team_id,
                            "pin": "012345",
                            "height_cm": 175,
                            "weight_kg": 72,
                            "position": "MEI",
                            "secondary_position": None,
                            "preferred_foot": "Direito",
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.text)
                    player_id = response.json()["user"]["id"]

                    match_response = await coach.post(
                        "/api/matches",
                        json={
                            "opponent": "Adversário",
                            "played_on": "2026-10-30",
                            "kickoff_time": "18:30",
                            "venue": "Campo de teste",
                            "formation": "Livre",
                            "roster": [
                                {
                                    "player_id": player_id,
                                    "position": "MEI",
                                    "is_starter": True,
                                    "field_x": 50,
                                    "field_y": 50,
                                }
                            ],
                        },
                    )
                    self.assertEqual(match_response.status_code, 201, match_response.text)
                    match_id = match_response.json()["match"]["id"]

                    result_response = await coach.put(
                        f"/api/matches/{match_id}/result",
                        json={
                            "home_score": 1,
                            "away_score": 0,
                            "stats": [
                                {
                                    "player_id": player_id,
                                    "goals": 1,
                                    "assists": 0,
                                    "yellow_cards": 0,
                                    "red_cards": 0,
                                }
                            ],
                        },
                    )
                    self.assertEqual(result_response.status_code, 200, result_response.text)
                    self.assertEqual(result_response.json()["match"]["home_score"], 1)

                    forbidden_response = await player.post(
                        "/api/matches",
                        json={
                            "opponent": "Outro adversário",
                            "played_on": "2026-10-31",
                            "kickoff_time": "19:00",
                            "roster": [],
                        },
                    )
                    self.assertEqual(forbidden_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
