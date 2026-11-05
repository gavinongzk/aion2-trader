import unittest

from aion2.collect import match_server

# made-up listing in the shape of /api/servers
SERVERS = [
    {"server_id": 1, "name": "Hadala", "faction": "Elyos", "region": "asia", "region_name": "Asia"},
    {"server_id": 2, "name": "Hadala", "faction": "Asmodian", "region": "asia", "region_name": "Asia"},
    {"server_id": 3, "name": "Hadala", "faction": "Elyos", "region": "eu", "region_name": "Europe"},
    {"server_id": 4, "name": "Siel", "faction": "Elyos", "region": "asia", "region_name": "Asia"},
]


def ids(name):
    return [s["server_id"] for s in match_server(SERVERS, name)]


class MatchServer(unittest.TestCase):
    def test_name_and_region(self):
        self.assertEqual(ids("HADALA ASIA"), [1, 2])

    def test_faction_narrows_it(self):
        self.assertEqual(ids("Hadala Asia Asmodian"), [2])

    def test_name_with_region_in_it(self):
        self.assertEqual(match_server([{"server_id": 9, "name": "Hadala-Asia"}], "hadala asia")[0]["server_id"], 9)

    def test_no_match(self):
        self.assertEqual(ids("Hadala Korea"), [])


if __name__ == "__main__":
    unittest.main()
