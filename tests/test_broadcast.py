# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.services import broadcast


class BroadcastDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "subscribers.db"
        # Patch module-level path for the duration of each test
        broadcast.DB_PATH = self.db_path
        # Ensure module creates a fresh database file
        broadcast._init_db()  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_add_user_is_idempotent(self) -> None:
        broadcast.add_user(123)
        broadcast.add_user(123)
        broadcast.add_user(456)
        users = broadcast.get_all_users()
        self.assertCountEqual(users, [123, 456])
        self.assertEqual(broadcast.users_count(), 2)

    def test_register_user_from_message(self) -> None:
        message = SimpleNamespace(chat=SimpleNamespace(id=999))
        # Should add chat id to sqlite database
        broadcast.add_user(111)
        self.assertEqual(broadcast.users_count(), 1)
        broadcast._init_db()  # ensure DB exists
        # call async helper using event loop
        import asyncio

        asyncio.run(broadcast.register_user_from_message(message))
        self.assertCountEqual(broadcast.get_all_users(), [111, 999])


class BroadcastUtilitiesTests(unittest.TestCase):
    def test_chunk_text_splits_long_messages(self) -> None:
        text = "x" * 5000
        parts = broadcast.chunk_text(text, limit=2048)
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "x" * 2048)
        self.assertEqual(parts[1], "x" * 2048)
        self.assertEqual(parts[2], "x" * 904)


if __name__ == "__main__":
    unittest.main()
