import json
from enum import Enum

from videobench import contracts, types


def test_existing_enum_string_and_json_contracts() -> None:
    checked = 0
    for module in (contracts, types):
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Enum)
                and value.__module__ == module.__name__
            ):
                for member in value:
                    assert str(member) == f"{value.__name__}.{member.name}"
                    assert json.dumps(member) == json.dumps(member.value)
                    checked += 1
    assert checked > 0
