#!/usr/bin/env python3
"""Neon Vault: a small, dependency-free terminal roguelike."""

import argparse
from collections import deque
import os
import random
import shutil
import sys
import textwrap
from dataclasses import dataclass

WIDTH, HEIGHT = 41, 15
DIRECTIONS = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}
ALIASES = {"up": "w", "down": "s", "left": "a", "right": "d"}
HELP = """Retrieve the data core (*) on each floor, then reach the lift (>).
Escape all three floors to win. Walk into a robot to attack it.

WASD / arrows   Move or attack      E   EMP blast (3-tile radius)
H               Use a medkit        . / Space / Enter   Wait
?               This help           Q   Quit the run

@ You    # Wall    d Drone    G Guard    * Core    > Lift
$ Credits (+25 score)    + Medkit    ^ Shock tile (2 damage)

Every move, attack, blast, heal, or wait gives the robots a turn.
Walls, invalid commands, help, and empty supplies cost no turns.
Drones fall to one hit. Guards are tougher but act every other turn.
An EMP damages and briefly stuns nearby robots, even through walls.
Medkits restore 8 HP. Your EMP charges refill on each new floor.
Collecting a core reveals the map. Choose an upgrade between floors.
"""


@dataclass
class Enemy:
    x: int
    y: int
    kind: str = "d"
    hp: int = 3
    stun: int = 0


class Game:
    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.floor = 1
        self.hp = self.max_hp = 20
        self.attack = 3
        self.medkits = 2
        self.max_charges = 3
        self.score = 0
        self.turn = 0
        self.state = "playing"
        self.log = deque(maxlen=3)
        self.make_floor()

    def say(self, message):
        self.log.append(message)

    def distances(self, start):
        """Flood-fill the walkable map; also used for robot navigation."""
        distance = {start: 0}
        pending = deque([start])
        while pending:
            x, y = pending.popleft()
            for dx, dy in DIRECTIONS.values():
                pos = x + dx, y + dy
                if pos in self.tiles and pos not in distance:
                    distance[pos] = distance[x, y] + 1
                    pending.append(pos)
        return distance

    def make_floor(self):
        self.tiles = set()
        centers = []
        # Six rooms joined in a loop, so every item is always reachable.
        for row in range(2):
            for col in range(3):
                left = 2 + col * 13 + self.rng.randrange(2)
                top = 1 + row * 7 + self.rng.randrange(2)
                width = self.rng.randint(7, 10)
                height = self.rng.randint(3, 5)
                self.tiles.update((x, y) for x in range(left, left + width)
                                  for y in range(top, top + height))
                centers.append((left + width // 2, top + height // 2))
        route = [0, 1, 2, 5, 4, 3, 0]
        for source, target in zip(route, route[1:]):
            x, y = centers[source]
            tx, ty = centers[target]
            if self.rng.choice([True, False]):
                self.tiles.update((cx, y) for cx in range(min(x, tx), max(x, tx) + 1))
                self.tiles.update((tx, cy) for cy in range(min(y, ty), max(y, ty) + 1))
            else:
                self.tiles.update((x, cy) for cy in range(min(y, ty), max(y, ty) + 1))
                self.tiles.update((cx, ty) for cx in range(min(x, tx), max(x, tx) + 1))
        self.player = centers[0]
        distance = self.distances(self.player)
        # Sorting before randomization makes a seed portable across platforms.
        available = sorted(pos for pos in self.tiles if distance[pos] > 5)
        self.rng.shuffle(available)
        farthest = sorted(available, key=lambda pos: distance[pos], reverse=True)
        self.exit = farthest[0]
        from_exit = self.distances(self.exit)
        core = max(available, key=lambda pos: min(distance[pos], from_exit[pos]))
        available.remove(self.exit)
        available.remove(core)
        self.items = {core: "*"}
        for item in ["+"] * 2 + ["$"] * 6 + ["^"] * (3 + self.floor):
            self.items[available.pop()] = item
        self.enemies = []
        for index in range(4 + self.floor * 2):
            x, y = available.pop()
            guard = index % 3 == 2
            self.enemies.append(Enemy(x, y, "G" if guard else "d", 6 if guard else 3))
        self.has_core = False
        self.charges = self.max_charges
        self.seen = set()
        self.visible = set()
        self.reveal()
        self.say(f"Floor {self.floor}/3. Find the core (*), then the lift (>).")

    def reveal(self):
        # Small maps use a simple scanner radius, including through walls.
        px, py = self.player
        self.visible = {(x, y) for y in range(HEIGHT) for x in range(WIDTH)
                        if abs(x - px) + abs(y - py) <= 6}
        self.seen.update(self.visible)

    def hit(self, enemy, damage):
        enemy.hp -= damage
        if enemy.hp <= 0:
            self.enemies.remove(enemy)
            self.score += 40 if enemy.kind == "G" else 20
            return True
        return False

    def take_turn(self, command):
        """Return whether an action used a turn. UI-only inputs are free."""
        if self.state != "playing":
            return False
        command = ALIASES.get(command, command)
        if command in DIRECTIONS:
            dx, dy = DIRECTIONS[command]
            target = self.player[0] + dx, self.player[1] + dy
            if target not in self.tiles:
                self.say("Solid wall. Try another route.")
                return False
            enemy = next((e for e in self.enemies if (e.x, e.y) == target), None)
            if enemy:
                killed = self.hit(enemy, self.attack)
                self.say("Robot scrapped." if killed else f"Hit! Guard has {enemy.hp} HP left.")
            else:
                self.player = target
                item = self.items.get(target)
                if item == "*":
                    self.has_core = True
                    self.score += 150
                    self.seen.update((x, y) for y in range(HEIGHT) for x in range(WIDTH))
                    self.say("CORE SECURED! Map revealed. Head for the lift (>).")
                elif item == "$":
                    self.score += 25
                    self.say("Pocketed 25 credits.")
                elif item == "+":
                    self.medkits += 1
                    self.say("Medkit collected. Press H when you need it.")
                elif item == "^":
                    self.hp = max(0, self.hp - 2)
                    self.say("Shock tile! Lost 2 HP.")
                if item and item != "^":
                    del self.items[target]
                if target == self.exit:
                    if self.has_core:
                        self.score += 200
                        self.state = "won" if self.floor == 3 else "upgrade"
                    else:
                        self.say("Lift locked. Retrieve this floor's core (*) first.")
        elif command == "e":
            if not self.charges:
                self.say("No EMP charges. They refill on the next floor.")
                return False
            self.charges -= 1
            targets = [e for e in self.enemies
                       if abs(e.x - self.player[0]) + abs(e.y - self.player[1]) <= 3]
            for enemy in targets:
                enemy.stun = 2
                self.hit(enemy, 3)
            self.say(f"EMP discharged! Hit {len(targets)} robot(s).")
        elif command == "h":
            if not self.medkits or self.hp == self.max_hp:
                self.say("No medkits left." if not self.medkits else "Health already full.")
                return False
            self.medkits -= 1
            healed = min(8, self.max_hp - self.hp)
            self.hp += healed
            self.say(f"Patched up: +{healed} HP.")
        elif command in ("", " ", "."):
            self.say("You wait and listen to the machinery.")
        else:
            self.say("Use WASD, E for EMP, H to heal, or ? for help.")
            return False
        self.turn += 1
        if self.hp <= 0:
            self.state = "lost"
        if self.state == "playing":
            self.move_enemies()
        self.reveal()
        return True

    def move_enemies(self):
        distance = self.distances(self.player)
        occupied = {(e.x, e.y) for e in self.enemies}
        damage = 0
        for enemy in self.enemies:
            if enemy.stun:
                enemy.stun -= 1
                continue
            if enemy.kind == "G" and self.turn % 2:
                continue
            pos = enemy.x, enemy.y
            steps = distance.get(pos, WIDTH * HEIGHT)
            if steps == 1:
                damage += 2 if enemy.kind == "G" else 1
            elif steps <= 8:
                choices = [(enemy.x + dx, enemy.y + dy) for dx, dy in DIRECTIONS.values()]
                self.rng.shuffle(choices)
                choices = [p for p in choices if p in distance and p not in occupied
                           and p != self.player and distance[p] < steps]
                if choices:
                    occupied.remove(pos)
                    enemy.x, enemy.y = min(choices, key=distance.get)
                    occupied.add((enemy.x, enemy.y))
        if damage:
            self.hp = max(0, self.hp - damage)
            self.say(f"Robots hit you for {damage} damage! H heals; E blasts nearby bots.")
        if self.hp == 0:
            self.state = "lost"

    def upgrade(self, choice):
        if self.state != "upgrade" or choice not in ("1", "2", "3"):
            return False
        if choice == "1":
            self.max_hp += 5
            self.hp = self.max_hp
            message = "Armor upgraded. +5 max HP and fully repaired."
        elif choice == "2":
            self.attack += 2
            self.hp = min(self.max_hp, self.hp + 6)
            message = "Blade upgraded. +2 attack and +6 HP."
        else:
            self.max_charges += 2
            self.hp = min(self.max_hp, self.hp + 6)
            message = "Capacitor upgraded. +2 EMP capacity and +6 HP."
        self.floor += 1
        self.state = "playing"
        self.make_floor()
        self.say(message)
        return True


class Terminal:
    """Use native key input where possible; fall back to ordinary text input."""
    def __init__(self, plain=False, line_input=False):
        self.color = sys.stdout.isatty() and not plain and "NO_COLOR" not in os.environ
        self.ansi = sys.stdout.isatty() and not plain
        self.line_input = line_input or not sys.stdin.isatty() or not sys.stdout.isatty()
        self.saved_mode = None
        self.windows_console = None
        if os.name == "nt" and self.ansi:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetStdHandle.argtypes = [wintypes.DWORD]
            kernel.GetStdHandle.restype = wintypes.HANDLE
            kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            handle = kernel.GetStdHandle(-11)
            mode = wintypes.DWORD()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)) and kernel.SetConsoleMode(handle, mode.value | 4):
                self.windows_console = kernel, handle, mode.value
            else:
                self.ansi = self.color = False
        elif os.name != "nt" and os.environ.get("TERM") == "dumb":
            self.ansi = self.color = False
            self.line_input = True

    def __enter__(self):
        if not self.line_input and os.name != "nt":
            import termios
            import tty
            try:
                self.saved_mode = termios.tcgetattr(sys.stdin.fileno())
                tty.setcbreak(sys.stdin.fileno())
            except (OSError, termios.error):
                self.line_input = True
        if self.ansi and not self.line_input:
            print("\033[?25l", end="", flush=True)
        return self

    def __exit__(self, *_):
        if self.saved_mode is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved_mode)
        if self.ansi:
            print("\033[0m\033[?25h", end="", flush=True)
        if self.windows_console:
            kernel, handle, mode = self.windows_console
            kernel.SetConsoleMode(handle, mode)

    def ink(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def screen(self, text):
        prefix = "\033[2J\033[H" if self.ansi else "\n"
        print(prefix + text, flush=True)

    def key(self):
        if self.line_input:
            line = sys.stdin.readline()
            return line.strip().lower() if line else "EOF"
        if os.name == "nt":
            import msvcrt
            key = msvcrt.getwch()
            if key in ("\x00", "\xe0"):
                return {"H": "w", "P": "s", "K": "a", "M": "d"}.get(msvcrt.getwch(), "unknown")
        else:
            import select
            key = os.read(sys.stdin.fileno(), 1).decode("ascii", errors="replace")
            if key == "\x1b":
                # Read escape sequences without leaving arrow bytes as commands.
                sequence = ""
                while len(sequence) < 12 and select.select([sys.stdin], [], [], 0.04)[0]:
                    byte = os.read(sys.stdin.fileno(), 1)
                    if not byte:
                        return "EOF"
                    sequence += byte.decode("ascii", errors="replace")
                    if len(sequence) >= 2 and "@" <= sequence[-1] <= "~":
                        break
                return {"[A": "w", "[B": "s", "[C": "d", "[D": "a",
                        "OA": "w", "OB": "s", "OC": "d", "OD": "a"}.get(sequence, "unknown")
        if key == "\x03":
            raise KeyboardInterrupt
        if key in ("", "\x04", "\x1a"):
            return "EOF"
        return "" if key in ("\r", "\n") else key.lower()


def show_game(terminal, game):
    bar = "=" * round(16 * game.hp / game.max_hp)
    health = f"[{bar:<16}] {game.hp:2}/{game.max_hp}"
    lines = [terminal.ink("  N E O N   V A U L T", "1;96") + f"     FLOOR {game.floor}/3    SCORE {game.score}",
             f"  HP {terminal.ink(health, '92' if game.hp > 6 else '91')}  ATK {game.attack}  EMP {game.charges}/{game.max_charges}  MED {game.medkits}",
             f"  CORE: {'SECURED - reach >' if game.has_core else 'find *'}     TURN {game.turn}    SEED {game.seed}",
             "  +" + "-" * WIDTH + "+"]
    legend = ["SCANNER ONLINE", "", "@  You", "d  Drone / 3 HP", "G  Guard / 6 HP", "*  Data core",
              ">  Escape lift", "$  Credits", "+  Medkit", "^  Shock tile", "", "E  EMP: radius 3",
              "H  Heal: +8 HP", "?  Help", "Q  Quit"]
    enemy_at = {(e.x, e.y): e for e in game.enemies}
    colors = {"@": "1;96", "#": "90", "d": "91", "G": "1;91", "*": "1;93",
              ">": "1;92", "$": "93", "+": "92", "^": "95", ".": "90"}
    for y in range(HEIGHT):
        row = []
        for x in range(WIDTH):
            pos = x, y
            char = " "
            if pos in game.seen:
                char = "." if pos in game.tiles else "#"
                if pos in game.items:
                    char = game.items[pos]
                if pos == game.exit:
                    char = ">"
                if pos in enemy_at and pos in game.visible:
                    char = enemy_at[pos].kind
                if pos == game.player:
                    char = "@"
            color = colors.get(char, "0")
            if pos not in game.visible and char in ("#", "."):
                color = "2;90"
            row.append(terminal.ink(char, color) if char != " " else " ")
        lines.append("  |" + "".join(row) + "|  " + legend[y])
    lines.append("  +" + "-" * WIDTH + "+")
    lines.append("  WASD/arrows: move/attack | E: blast | H: heal | .: wait")
    terminal_height = shutil.get_terminal_size((80, 28)).lines
    log_count = max(1, min(3, terminal_height - 22 - int(terminal.line_input)))
    for message in list(game.log)[-log_count:]:
        lines.append("  " + message)
    if terminal.line_input:
        lines.append("  Type a command and press Enter:")
    terminal.screen("\n".join(lines))


def show_help(terminal):
    terminal.screen("  NEON VAULT / FIELD MANUAL\n\n" + textwrap.indent(HELP, "  ") + "\n  Press Enter to return.")
    while True:
        key = terminal.key()
        if key == "EOF":
            return False
        if key == "":
            return True


def play(terminal, seed):
    game = Game(seed)
    while True:
        if game.state in ("won", "lost"):
            result = "VAULT BREACHED. YOU MADE IT OUT." if game.state == "won" else "SIGNAL LOST. THE VAULT CLAIMS ANOTHER RUN."
            if game.state == "won":
                game.score += game.hp * 10
            terminal.screen(f"\n  {terminal.ink(result, '1;96')}\n\n"
                            f"  Score: {game.score}    Floor: {game.floor}/3    Turns: {game.turn}\n"
                            f"  Seed: {game.seed}\n\n  [R] New run    [S] Replay this seed    [Q] Quit")
            while True:
                key = terminal.key()
                if key in ("r", "s", "q", "EOF"):
                    return key
        if game.state == "upgrade":
            terminal.screen(f"\n  FLOOR {game.floor} CLEARED / UPGRADE STATION\n\n"
                            f"  HP {game.hp}/{game.max_hp}    Score {game.score}\n\n"
                            "  [1] REINFORCED ARMOR   +5 max HP, full repair\n"
                            "  [2] PLASMA BLADE      +2 attack, heal 6 HP\n"
                            "  [3] EMP CAPACITOR     +2 EMP capacity, heal 6 HP\n\n"
                            "  Choose 1, 2, or 3. All EMP charges refill. Q quits.")
            key = terminal.key()
            if key in ("q", "EOF"):
                return key
            game.upgrade(key)
            continue
        show_game(terminal, game)
        key = terminal.key()
        if key == "EOF":
            return key
        if key == "q":
            terminal.screen("\n  Abandon this run? Press Y to quit, any other key to continue.")
            if terminal.key() in ("y", "EOF"):
                return "q"
        elif key == "?":
            if not show_help(terminal):
                return "EOF"
        else:
            game.take_turn(key)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Neon Vault - a terminal dungeon escape. Python 3.10+, no dependencies.")
    parser.add_argument("--plain", action="store_true", help="disable colors and screen-clearing escape sequences")
    parser.add_argument("--line-input", action="store_true", help="type commands followed by Enter")
    parser.add_argument("--seed", type=int, help="replay a particular map seed")
    args = parser.parse_args(argv)
    try:
        with Terminal(args.plain, args.line_input) as terminal:
            while True:
                terminal.screen(terminal.ink(
                    "\n  +-----------------------------------------------------+\n"
                    "  |                                                     |\n"
                    "  |          N E O N   /   V A U L T                      |\n"
                    "  |           A TERMINAL HEIST                           |\n"
                    "  |                                                     |\n"
                    "  +-----------------------------------------------------+", "1;96") +
                    "\n\n  Three floors. Three stolen cores. One way out.\n"
                    "  Outwit the machines and escape with the data.\n\n"
                    "  [Enter / 1] Start heist\n  [2]         Field manual\n  [Q]         Quit\n\n"
                    "  WASD or arrow keys to move. Walk into robots to attack.\n"
                    "  Take your time: enemies only act when you do.\n" +
                    ("\n  Input mode: type a command, then press Enter." if terminal.line_input else "\n  Input mode: press keys directly. No Enter needed."))
                key = terminal.key()
                if key in ("q", "EOF"):
                    break
                if key == "2":
                    if not show_help(terminal):
                        break
                elif key in ("", "1"):
                    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1_000_000)
                    while True:
                        result = play(terminal, seed)
                        if result == "r":
                            seed = random.SystemRandom().randrange(1_000_000)
                        elif result != "s":
                            break
                    if result in ("q", "EOF"):
                        break
    except (KeyboardInterrupt, EOFError):
        pass
    except BrokenPipeError:
        return 0
    print("\n  Thanks for playing Neon Vault.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
