"""Test-only abrupt process exit AFTER a real local API write response."""
import os
from fashion_scout.client import Connection, main

original = Connection.request


def lose_receipt(self, method, path, payload=None, query=None):
    result = original(self, method, path, payload, query)
    if method in {'POST', 'PATCH'}:
        os._exit(73)
    return result


if __name__ == '__main__':
    Connection.request = lose_receipt
    raise SystemExit(main())
