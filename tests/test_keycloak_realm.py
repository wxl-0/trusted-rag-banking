import json
from pathlib import Path


REALM_EXPORT = Path(__file__).parents[1] / "keycloak" / "realm-export.json"


def test_realm_provides_two_public_demo_identities_ready_for_login():
    realm = json.loads(REALM_EXPORT.read_text(encoding="utf-8"))
    users = {user["username"]: user for user in realm["users"]}
    expected = {
        "admin01": ("member", "12301"),
        "admin02": ("knowledge_maintainer", "12302"),
    }

    assert users.keys() == expected.keys()
    for username, (role, password) in expected.items():
        user = users[username]
        assert user["realmRoles"] == [role]
        assert user["email"].endswith("@example.invalid")
        assert user["credentials"] == [{
            "type": "password",
            "value": password,
            "temporary": False,
        }]
