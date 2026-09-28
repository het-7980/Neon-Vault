"""Run with: python -m unittest discover -s tests -v."""

import unittest
from unittest.mock import patch

from game import Enemy, Game, HEIGHT, WIDTH, Terminal


def arena():
    game = Game(42)
    game.tiles = {(x, y) for x in range(1, 10) for y in range(1, 5)}
    game.player = (2, 2)
    game.exit = (9, 4)
    game.items = {}
    game.enemies = []
    return game


class GameTests(unittest.TestCase):
    def test_generated_floors_are_connected_and_placements_are_safe(self):
        for seed in range(100):
            game = Game(seed)
            for floor in range(1, 4):
                with self.subTest(seed=seed, floor=floor):
                    distances = game.distances(game.player)
                    self.assertEqual(set(distances), game.tiles)
                    self.assertTrue(all(0 < x < WIDTH - 1 and 0 < y < HEIGHT - 1
                                        for x, y in game.tiles))
                    placements = [game.exit, *game.items,
                                  *((e.x, e.y) for e in game.enemies)]
                    self.assertEqual(len(placements), len(set(placements)))
                    self.assertTrue(all(distances[pos] > 5 for pos in placements))
                    self.assertEqual(list(game.items.values()).count("*"), 1)
                    self.assertEqual(len(game.enemies), 4 + floor * 2)
                    self.assertFalse(game.has_core)
                    self.assertEqual(game.charges, game.max_charges)
                if floor < 3:
                    game.state = "upgrade"
                    self.assertTrue(game.upgrade("2"))

    def test_seed_replays_all_three_floors(self):
        first, second = Game(98765), Game(98765)
        for floor in range(1, 4):
            with self.subTest(floor=floor):
                for attribute in ("tiles", "player", "exit", "items", "enemies"):
                    self.assertEqual(getattr(first, attribute), getattr(second, attribute))
            if floor < 3:
                for game in (first, second):
                    game.state = "upgrade"
                    game.upgrade("3")

    def test_melee_and_emp_damage_stun_and_empty_charge(self):
        game = arena()
        game.enemies = [Enemy(3, 2)]
        self.assertTrue(game.take_turn("d"))
        self.assertEqual((game.player, game.score, game.hp), ((2, 2), 20, 20))
        self.assertEqual(game.enemies, [])

        game = arena()
        nearby, distant = Enemy(3, 2, "G", 6), Enemy(8, 2, "G", 6)
        game.enemies = [nearby, distant]
        self.assertTrue(game.take_turn("e"))
        self.assertEqual((nearby.hp, nearby.stun, distant.hp), (3, 1, 6))
        self.assertEqual((game.charges, game.hp), (2, 20))
        game.take_turn(".")
        self.assertEqual((nearby.stun, game.hp), (0, 20))
        game.take_turn(".")
        game.take_turn(".")
        self.assertEqual(game.hp, 18)
        self.assertTrue(game.take_turn("d"))
        self.assertNotIn(nearby, game.enemies)
        self.assertEqual(game.score, 40)
        game.charges = 0
        previous = (game.turn, game.hp, distant.x, distant.y)
        self.assertFalse(game.take_turn("e"))
        self.assertEqual((game.turn, game.hp, distant.x, distant.y), previous)

    def test_core_unlocks_lift_and_third_floor_wins(self):
        game = arena()
        for floor in range(1, 4):
            game.player, game.exit = (2, 2), (3, 2)
            game.items, game.enemies = {(4, 2): "*"}, []
            game.tiles = {(2, 2), (3, 2), (4, 2)}
            game.take_turn("d")
            self.assertEqual(game.state, "playing")
            game.take_turn("d")
            self.assertTrue(game.has_core)
            self.assertNotIn((4, 2), game.items)
            self.assertEqual(len(game.seen), WIDTH * HEIGHT)
            game.take_turn("a")
            self.assertEqual(game.state, "won" if floor == 3 else "upgrade")
            self.assertEqual(game.score, floor * 350)
            self.assertFalse(game.take_turn("."))
            if floor < 3:
                self.assertTrue(game.upgrade("1"))
        self.assertFalse(game.upgrade("1"))

    def test_upgrades_repair_refill_and_reset_floor_objective(self):
        for choice, max_hp, attack, capacity, hp in (
                ("1", 25, 3, 3, 25), ("2", 20, 5, 3, 13), ("3", 20, 3, 5, 13)):
            with self.subTest(choice=choice):
                game = arena()
                self.assertFalse(game.upgrade(choice))
                game.state, game.hp, game.charges, game.has_core = "upgrade", 7, 0, True
                self.assertFalse(game.upgrade("invalid"))
                self.assertEqual(game.floor, 1)
                self.assertTrue(game.upgrade(choice))
                self.assertEqual((game.floor, game.state, game.has_core), (2, "playing", False))
                self.assertEqual((game.max_hp, game.attack, game.max_charges, game.hp),
                                 (max_hp, attack, capacity, hp))
                self.assertEqual(game.charges, capacity)

    def test_free_actions_healing_and_lethal_shock(self):
        game = arena()
        game.player = (1, 1)
        for command in ("a", "invalid", "h"):
            self.assertFalse(game.take_turn(command))
        self.assertEqual((game.turn, game.medkits), (0, 2))
        game.hp = 17
        self.assertTrue(game.take_turn("h"))
        self.assertEqual((game.hp, game.medkits, game.turn), (20, 1, 1))
        game.medkits, game.hp = 0, 2
        self.assertFalse(game.take_turn("h"))
        game.items[(2, 1)] = "^"
        game.take_turn("d")
        self.assertEqual((game.hp, game.state), (0, "lost"))
        self.assertFalse(game.take_turn("h"))


class KeyboardTests(unittest.TestCase):
    def test_posix_arrows_eof_and_unrecognized_bytes(self):
        terminal = Terminal.__new__(Terminal)
        terminal.line_input = False
        cases = [([b"\x1b", b"[", b"A"], "w"),
                 ([b"\x1b", b"O", b"D"], "a"),
                 ([b"\x1b", b""], "EOF"), ([b""], "EOF")]
        with patch("game.os.name", "posix"), patch("game.sys.stdin"), \
                patch("select.select", return_value=([0], [], [])):
            for sequence, expected in cases:
                with self.subTest(sequence=sequence), patch("game.os.read", side_effect=sequence):
                    self.assertEqual(terminal.key(), expected)
            with patch("game.os.read", return_value=b"\xc3"):
                command = terminal.key()
                self.assertNotEqual(command, "EOF")
                self.assertFalse(arena().take_turn(command))


if __name__ == "__main__":
    unittest.main()
