"""Mocked tests for classification logic — no live QRS server required."""
import sys
import os
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cleanup import fetch_users_for_strategy  # noqa: E402
from inactive_users import classify_inactive_users  # noqa: E402


def _user(user_id, directory, name, custom_properties=None, blacklisted=None):
    u = {"id": user_id, "userDirectory": directory, "userId": name}
    if custom_properties is not None:
        u["customProperties"] = custom_properties
    if blacklisted is not None:
        u["blacklisted"] = blacklisted
    return u


def test_custom_property_strategy_matches_true_value():
    users = [
        _user("1", "CORP", "alice", custom_properties=[
            {"definition": {"name": "Inactive"}, "value": "true"}
        ]),
        _user("2", "CORP", "bob", custom_properties=[
            {"definition": {"name": "Inactive"}, "value": "false"}
        ]),
        _user("3", "CORP", "carol"),  # no custom properties at all
    ]
    candidates = classify_inactive_users(
        users, strategy="custom_property",
        custom_property_name="Inactive", custom_property_value="true",
    )
    assert [c.user_name for c in candidates] == ["alice"]


def test_blacklisted_strategy():
    users = [
        _user("1", "CORP", "alice", blacklisted=True),
        _user("2", "CORP", "bob", blacklisted=False),
        _user("3", "CORP", "carol"),
    ]
    candidates = classify_inactive_users(users, strategy="blacklisted")
    assert [c.user_name for c in candidates] == ["alice"]


def test_inactive_strategy():
    users = [
        {**_user("1", "CORP", "alice", blacklisted=True), "inactive": True},
        {**_user("2", "CORP", "bob"), "inactive": False},
        _user("3", "CORP", "carol"),
    ]
    candidates = classify_inactive_users(users, strategy="inactive")
    assert [c.user_name for c in candidates] == ["alice"]
    assert candidates[0].blacklisted is True


def test_inactive_fetch_filters_at_qrs():
    client = Mock()
    client.fetch_users.return_value = []

    fetch_users_for_strategy(client, "inactive")

    client.fetch_users.assert_called_once_with(filter_expr="inactive eq true")


def test_blacklisted_fetch_filters_at_qrs():
    client = Mock()
    client.fetch_users.return_value = []

    fetch_users_for_strategy(client, "blacklisted")

    client.fetch_users.assert_called_once_with(filter_expr="blacklisted eq true")


def test_custom_property_fetch_keeps_full_payload():
    client = Mock()
    client.fetch_users.return_value = []

    fetch_users_for_strategy(client, "custom_property")

    client.fetch_users.assert_called_once_with()


def test_unknown_strategy_raises():
    try:
        classify_inactive_users([], strategy="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_external_audit_requires_csv_path():
    try:
        classify_inactive_users([], strategy="external_audit", audit_csv_path=None)
        assert False, "expected ValueError"
    except ValueError:
        pass


if __name__ == "__main__":
    test_custom_property_strategy_matches_true_value()
    test_blacklisted_strategy()
    test_inactive_strategy()
    test_inactive_fetch_filters_at_qrs()
    test_blacklisted_fetch_filters_at_qrs()
    test_custom_property_fetch_keeps_full_payload()
    test_unknown_strategy_raises()
    test_external_audit_requires_csv_path()
    print("All tests passed.")
