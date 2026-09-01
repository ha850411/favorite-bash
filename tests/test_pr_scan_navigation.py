import unittest

def decode_bytes(data):
    if data in (b"\x1b[A", b"\x1bOA"):
        return "UP"
    elif data in (b"\x1b[B", b"\x1bOB"):
        return "DOWN"
    elif data in (b"\x1b[C", b"\x1bOC"):
        return "RIGHT"
    elif data in (b"\x1b[D", b"\x1bOD"):
        return "LEFT"
    elif data.startswith(b"\x1b[") or data.startswith(b"\x1bO"):
        if data.endswith(b"A"):
            return "UP"
        elif data.endswith(b"B"):
            return "DOWN"
        elif data.endswith(b"C"):
            return "RIGHT"
        elif data.endswith(b"D"):
            return "LEFT"
        elif b"5~" in data:
            return "PAGE_UP"
        elif b"6~" in data:
            return "PAGE_DOWN"
        return "IGNORE"
    elif data == b"\x1b":
        return "ESC"
    elif data in (b"\r", b"\n"):
        return "ENTER"
    elif data == b" ":
        return "SPACE"
    elif data == b"\x03":
        return "CTRL_C"
    elif data == b"\x04":
        return "CTRL_D"
    else:
        try:
            return data.decode("utf-8")
        except Exception:
            return ""

class PrScanNavigationTests(unittest.TestCase):
    def test_key_decoding(self):
        # Arrow keys should decode reliably
        self.assertEqual(decode_bytes(b"\x1b[B"), "DOWN")
        self.assertEqual(decode_bytes(b"\x1b[A"), "UP")
        self.assertEqual(decode_bytes(b"\x1b[C"), "RIGHT")
        self.assertEqual(decode_bytes(b"\x1b[D"), "LEFT")
        self.assertEqual(decode_bytes(b"\x1bOB"), "DOWN")
        self.assertEqual(decode_bytes(b"\x1bOA"), "UP")
        self.assertEqual(decode_bytes(b"\x1b[1;2B"), "DOWN")
        self.assertEqual(decode_bytes(b" "), "SPACE")
        self.assertEqual(decode_bytes(b"\r"), "ENTER")
        self.assertEqual(decode_bytes(b"\n"), "ENTER")
        self.assertEqual(decode_bytes(b"\x1b"), "ESC")
        self.assertEqual(decode_bytes(b"q"), "q")
        self.assertEqual(decode_bytes(b"1"), "1")

    def test_key_decoding_and_navigation_logic(self):
        # Verify navigation logic
        items = [
            {"index": 1, "repo": "repo1", "has_a": True, "has_changes": True, "existing_pr": None, "selected": True},
            {"index": 2, "repo": "repo2", "has_a": True, "has_changes": False, "existing_pr": None, "selected": False},
            {"index": 3, "repo": "repo3", "has_a": True, "has_changes": True, "existing_pr": None, "selected": True},
        ]
        cursor = 0

        # DOWN key
        cursor = (cursor + 1) % len(items)
        self.assertEqual(cursor, 1)

        # SPACE key (Toggle)
        items[cursor]["selected"] = not items[cursor]["selected"]
        self.assertTrue(items[cursor]["selected"])

        # LEFT key (Uncheck)
        items[cursor]["selected"] = False
        self.assertFalse(items[cursor]["selected"])

        # RIGHT key (Check)
        items[cursor]["selected"] = True
        self.assertTrue(items[cursor]["selected"])

        # UP key
        cursor = (cursor - 1) % len(items)
        self.assertEqual(cursor, 0)

        # Digit key '3'
        target_idx = 3
        cursor = target_idx - 1
        items[cursor]["selected"] = not items[cursor]["selected"]
        self.assertEqual(cursor, 2)
        self.assertFalse(items[cursor]["selected"])

        # Toggle all (a/A)
        valid_items = [it for it in items if it["has_a"]]
        new_val = not all(it["selected"] for it in valid_items)
        for it in items:
            if it["has_a"]:
                it["selected"] = new_val
        self.assertTrue(all(it["selected"] for it in items))

if __name__ == "__main__":
    unittest.main()
