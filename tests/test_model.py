import json

import pytest

from resolver import InputError, parse_request


def valid_payload(**overrides):
    payload = {
        "packages": {
            "a": {
                "1": {"dependencies": {"b": [1, 2]}},
                "2": {},
            },
            "b": {"1": {"dependencies": {}}, "2": {"dependencies": {}}},
        },
        "root": {"a": [1, 2]},
        "installed": {"a": 1},
    }
    payload.update(overrides)
    return payload


def test_accepts_strict_request():
    catalog = parse_request(json.dumps(valid_payload()))
    assert catalog.ordered_names == ("a", "b")
    assert catalog.installed == {"a": 1}


@pytest.mark.parametrize(
    "document",
    [
        "not json",
        "[]",
        "null",
        '{"packages": {}, "root": {}, "installed": {}}',
    ],
)
def test_reject_malformed_documents(document):
    with pytest.raises(InputError):
        parse_request(document)


def test_reject_unknown_top_level_key():
    payload = valid_payload()
    payload["unexpected"] = True
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_too_many_packages():
    packages = {f"p{i}": {"1": {}} for i in range(11)}
    payload = valid_payload(packages=packages, root={"p0": [1, 1]}, installed={})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_too_many_versions():
    payload = valid_payload(packages={"a": {"1": {}, "2": {}, "3": {}, "4": {}, "5": {}}})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_non_integer_or_non_positive_version_key():
    for bad_key in ["0", "-1", "1.0", "v1"]:
        payload = valid_payload(packages={"a": {bad_key: {}}}, root={}, installed={})
        with pytest.raises(InputError):
            parse_request(json.dumps(payload))


def test_reject_non_ascii_package_name():
    payload = valid_payload(
        packages={"ä": {"1": {}}},
        root={},
        installed={},
    )
    with pytest.raises(InputError):
        parse_request(json.dumps(payload, ensure_ascii=False))


def test_reject_malformed_interval():
    payload = valid_payload(root={"a": [2, 1]})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_zero_interval_bound():
    payload = valid_payload(root={"a": [0, 1]})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_boolean_as_version_number():
    payload = valid_payload(installed={"a": True})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_dependency_outside_catalog():
    payload = valid_payload(
        packages={"a": {"1": {"dependencies": {"missing": [1, 1]}}}},
        root={"a": [1, 1]},
        installed={},
    )
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_root_outside_catalog():
    payload = valid_payload(root={"missing": [1, 1]})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_reject_installed_package_outside_catalog():
    payload = valid_payload(installed={"missing": 1})
    with pytest.raises(InputError):
        parse_request(json.dumps(payload))


def test_installed_version_need_not_still_exist_in_catalog():
    # Version 1 for installed a may be stale; current catalog only has 2/3.
    catalog = parse_request(json.dumps(valid_payload(installed={"a": 1, "b": 9})))
    assert catalog.installed == {"a": 1, "b": 9}


def test_reject_duplicate_json_object_keys():
    raw = """
    {
      "packages": {"a": {"1": {}, "1": {}}},
      "root": {},
      "installed": {}
    }
    """
    with pytest.raises(InputError):
        parse_request(raw)


def test_conflicts_default_to_empty():
    catalog = parse_request(json.dumps(valid_payload()))
    assert catalog.conflicts == ()


def test_accepts_empty_conflicts():
    catalog = parse_request(json.dumps(valid_payload(conflicts=[])))
    assert catalog.conflicts == ()


def test_accepts_valid_conflicts():
    payload = valid_payload(
        conflicts=[[{"package": "a", "version": 1}, {"package": "b", "version": 2}]]
    )
    catalog = parse_request(json.dumps(payload))
    assert catalog.conflicts == ((("a", 1), ("b", 2)),)


def test_conflicts_are_normalized_and_sorted():
    payload = valid_payload(
        conflicts=[
            [{"package": "b", "version": 2}, {"package": "a", "version": 1}],
            [{"package": "a", "version": 2}, {"package": "b", "version": 1}],
        ]
    )
    catalog = parse_request(json.dumps(payload))
    assert catalog.conflicts == ((("a", 1), ("b", 2)), (("a", 2), ("b", 1)))


@pytest.mark.parametrize(
    "conflicts",
    [
        None,  # present but null
        {},  # not an array
        "a",
        [[{"package": "a", "version": 1}]],  # single endpoint
        [  # three endpoints
            [
                {"package": "a", "version": 1},
                {"package": "b", "version": 1},
                {"package": "a", "version": 2},
            ]
        ],
        [["a", {"package": "b", "version": 1}]],  # endpoint not an object
        [[{"package": "a"}, {"package": "b", "version": 1}]],  # missing version
        [[{"version": 1}, {"package": "b", "version": 1}]],  # missing package
        [[{"package": "a", "version": 1, "extra": 1}, {"package": "b", "version": 1}]],
        [[{"package": "missing", "version": 1}, {"package": "b", "version": 1}]],
        [[{"package": "a", "version": 9}, {"package": "b", "version": 1}]],
        [[{"package": "a", "version": 0}, {"package": "b", "version": 1}]],
        [[{"package": "a", "version": True}, {"package": "b", "version": 1}]],
        [[{"package": 1, "version": 1}, {"package": "b", "version": 1}]],
        [[{"package": "a", "version": 1}, {"package": "a", "version": 2}]],
        [  # exact duplicate
            [{"package": "a", "version": 1}, {"package": "b", "version": 1}],
            [{"package": "a", "version": 1}, {"package": "b", "version": 1}],
        ],
        [  # reversed duplicate
            [{"package": "a", "version": 1}, {"package": "b", "version": 1}],
            [{"package": "b", "version": 1}, {"package": "a", "version": 1}],
        ],
    ],
)
def test_reject_invalid_conflicts(conflicts):
    with pytest.raises(InputError):
        parse_request(json.dumps(valid_payload(conflicts=conflicts)))
