# Copyright (c) 2016, Jacek Konieczny
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import asyncio
import logging
import shutil
import sys
import os

from collections import defaultdict
from configparser import ConfigParser, ExtendedInterpolation

from .input import input_devices_generator
from . import midi

logger = logging.getLogger("wizard")

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_CONFIG = os.path.join(PKG_DIR, "presets.conf")

class LineInput:
    def __init__(self, loop):
        self.loop = loop
        self.transport = None
        self.reader = asyncio.StreamReader()
        self.reader_protocol = asyncio.StreamReaderProtocol(self.reader)
    def __del__(self):
        self.stop()
    async def start(self):
        sys.stdin.flush()
        fd = os.dup(sys.stdin.fileno())
        res = await self.loop.connect_read_pipe(lambda: self.reader_protocol,
                                                os.fdopen(fd, "rb"))
        self.transport = res[0]
    def stop(self):
        if self.transport:
            self.transport.close()
            self.transport = None
    def pause(self):
        self.transport.pause_reading()
        sys.stdin.flush()
    def resume(self):
        sys.stdin.flush()
        self.transport.resume_reading()
    async def readline(self):
        line = await self.reader.readline()
        if not line:
            return None
        return line.decode('utf8').strip()

def parse_integer_list(items):
    """Yield values from a list of integer and integer ranges."""
    for item in items.split(","):
        if "-" in item:
            low, high = item.split("-", 1)
            try:
                low = int(low)
                high = int(high)
            except ValueError:
                logger.warning("Invalid range in list: %r in %r",
                               item, items)
                continue
            yield from range(low, high+1)
        else:
            try:
                yield int(item)
            except ValueError:
                logger.warning("Invalid integer in list: %r in %r",
                               item, items)
                continue

class Preset:
    def __init__(self, config, section):
        self.notemap = {}
        self.initial = False
        self.settings = {}
        self.name = section
        self.load(config, section)
    def load(self, config, section):
        self.notemap, self.settings = self.recursive_load(config, section)
        pconfig = config[section]
        self.initial = pconfig.getboolean("initial_template", False)
    def recursive_load(self, config, section, visited=None):
        if visited is None:
            visited = set()
        elif section in visited:
            logger.error("Presets include loop: %r", section)
            return {}
        visited.add(section)
        pconfig = config[section]
        include = pconfig.get("include")
        notes = {}
        settings = {}
        if include:
            for inc_list in include.split(";"):
                if ":" in inc_list:
                    i_preset, i_notes = inc_list.split(":", 1)
                else:
                    i_preset, i_notes = inc_list, None
                if i_preset not in config:
                    logger.error("Included preset %r not found", i_preset)
                    continue
                i_all_notes, i_settings = self.recursive_load(config,
                                                              i_preset,
                                                              visited)
                settings.update(i_settings)
                if i_notes is None:
                    notes.update(i_all_notes)
                else:
                    for i_note in parse_integer_list(i_notes):
                        try:
                            notes[i_note] = i_all_notes[i_note]
                        except KeyError:
                            logger.error("Included preset note %r not found",
                                         i_note)
                            continue
        for key in pconfig:
            try:
                note = int(key)
            except ValueError:
                continue
            if note < 0 or note > 127:
                continue
            notes[note] = pconfig[key]
        for setting in ("channel", "program", "bank", "velocity"):
            if setting in pconfig:
                settings[setting] = pconfig.getint(setting)
        return notes, settings

class KeymapWizard:
    def __init__(self, args, loop, input_devices, player):
        self.args = args
        self.loop = loop
        self.input_devices = input_devices
        self.input_device = None
        self.preset = None
        self.player = player
        self.presets = {}
        self.keymap = None
        self.saved = False
        self.load_presets()
        self.load_keymap()
        self.line_input = LineInput(loop)

    def load_presets(self):
        pconfig = ConfigParser(interpolation=ExtendedInterpolation(),
                                    default_section="defaults")
        pconfig.read([PRESETS_CONFIG])
        for section in pconfig:
            if section == pconfig.default_section:
                continue
            preset = Preset(pconfig, section)
            self.presets[preset.name] = preset

    def load_keymap(self):
        self.keymap = ConfigParser(interpolation=ExtendedInterpolation(),
                                    default_section="defaults")
        if os.path.exists(self.args.keymap_wizard):
            self.keymap.read([self.args.keymap_wizard])
            self.saved = True

    def play_note(self, note):
        """Play given note using current preset and keymap default settings."""
        if not self.player:
            return
        try:
            channel = self.preset.settings.get("channel")
            if channel is None:
                channel = self.keymap["defaults"].get("channel", 1)
            channel = int(channel)
        except ValueError:
            channel = 1
        if channel < 0 or channel > 15:
            channel = 1
        try:
            velocity = self.preset.settings.get("velocity")
            if velocity is None:
                velocity = self.keymap["defaults"].get("velocity", 127)
            velocity = int(velocity)
        except ValueError:
            velocity = 127
        if velocity < 0 or velocity > 15:
            velocity = 127
        msg = midi.NoteOn(channel, note, velocity)
        self.player.handle_message(msg)

    async def ask(self, prompt):
        print(prompt, end="")
        sys.stdout.flush()
        return await self.line_input.readline()

    def print_table(self, rows):
        """Print table of items.

        If the table is longer than 2/3 of the terminal size, try to display
        it in multiple columns."""
        print()
        rows = list(rows)
        widths = defaultdict(lambda: 0)
        for row in rows:
            for i, val in enumerate(row):
                val_len = len(str(val))
                if i == 0 and isinstance(val, int):
                    val_len = max(3, val_len + 1)
                widths[i] = max(widths[i], val_len)

        row_len = len(widths)
        row_width = sum(widths.values()) + row_len - 1
        term_size = shutil.get_terminal_size()
        split_thold = max(term_size.lines * 2 // 3, 8)
        columns = 1
        row_count = len(rows)
        table_row_count = row_count
        while table_row_count > split_thold:
            new_width = row_width * (columns + 1) + columns * 3
            if new_width >= term_size.columns:
                break
            columns += 1
            table_row_count = (row_count - 1) // columns + 1

        new_height = (row_count - 1) // columns + 1
        table_row_len = row_len * columns + (columns - 1) * 3
        for i, j in enumerate(range(0, row_count, columns)):
            for k in range(0, columns):
                try:
                    row = rows[j + k]
                except IndexError:
                    break
                if len(row) < row_len:
                    row += [""] * (row_len - len(row))
                k1 = (row_len + 1) * k
                if k > 0:
                    print(end=" ")
                for l, val in enumerate(row):
                    if l == 0:
                        if isinstance(val, int):
                            val = str(val) + "."
                        else:
                            val = str(val)
                        val = val.rjust(widths[l])
                    elif isinstance(val, int):
                        val = str(val).rjust(widths[l])
                    else:
                        val = str(val).ljust(widths[l])
                    print(val, end=" ")
            print()
        print()

    async def select_item(self, items, prompt):
        """Select item from a list."""
        while True:
            print()
            print(prompt)
            if items and isinstance(items[0], tuple):
                self.print_table([(i,) + t for i, t in enumerate(items, 1)])
            else:
                self.print_table(enumerate(items, 1))
            print(" 0. Quit")
            print()
            answer = await self.ask("> ")
            if answer is None:
                return None
            try:
                answer = int(answer)
            except ValueError:
                continue
            if answer == 0:
                return None
            elif answer >= 0 and answer <= len(items):
                return answer - 1

    async def select_device(self):
        """Input device selection dialog."""
        sorted_devices = sorted(self.input_devices, key=lambda x: x.name)
        dev_list = [dev.name for dev in sorted_devices]
        ans = await self.select_item(dev_list, "Choose the input device:")
        if ans is None:
            return None
        else:
            return sorted_devices[ans]

    async def select_preset(self, initial=True):
        """Select preset."""
        choice = []
        for name in sorted(self.presets):
            preset = self.presets[name]
            if initial:
                if not preset.initial:
                    continue
            choice.append(preset)
        ans = await self.select_item([p.name for p in choice],
                                     "Choose the preset:")
        if ans is None:
            return None
        else:
            return choice[ans]

    async def configure_from_preset(self):
        """Configure key for each note in preset."""
        for name, value in self.preset.settings.items():
            self.keymap["defaults"][name] = str(value)
        for note in self.preset.notemap:
            print()
            print("Press key for note {0:3}: {1} "
                  .format(note, self.preset.notemap[note]),
                  end="")
            sys.stdout.flush()
            self.line_input.pause()
            try:
                key_name = await self.input_device.get_key()
                if key_name is None:
                    return
                print(" [{}]".format(key_name))
                self.saved = False
                if key_name not in self.keymap:
                    self.keymap.add_section(key_name)
                self.keymap[key_name]["note"] = str(note)
                self.play_note(note)
            finally:
                self.line_input.resume()

    def _get_bindings(self):
        """Get list of current bindings."""
        full_preset = self.presets.get("Full")
        defaults = self.keymap["defaults"]
        for name in sorted(self.keymap):
            if name == "defaults":
                continue
            values = self.keymap[name]
            note = values.getint("note")
            if not note:
                note_descr = "unknown"
            elif note in self.preset.notemap:
                note_descr = self.preset.notemap[note]
            elif full_preset and note in full_preset.notemap:
                note_descr = full_preset.notemap[note]
            modifiers = []
            for key, value in values.items():
                if key in ("note",):
                    continue
                if value == defaults.get(key):
                    continue
                modifiers.append("{}={}".format(key, value))
            if modifiers:
                note_descr += " (" + ",".join(modifiers) + ")"
            yield name, note, note_descr

    async def show_bindings(self):
        """Show current keymap."""
        defaults = self.keymap["defaults"]
        if defaults:
            print()
            print("Global settings:")
            print()
            for key in sorted(defaults):
                value = defaults[key]
                print(" {}={}".format(key, value))
            print()
        print("Bindings:")
        self.print_table(self._get_bindings())

    async def unbind_menu(self):
        """Unbind menu"""
        bindings = list(self._get_bindings())
        ans = await self.select_item(bindings, "Select binding to remove:")
        if ans is None:
            return
        del self.keymap[bindings[ans][0]]

    async def bind_menu(self):
        """Bind menu"""
        notemap = self.preset.notemap
        choice = [(note, notemap[note]) for note in sorted(notemap)]
        ans = await self.select_item(choice, "Select note:")
        if ans is None:
            return
        note, name = choice[ans]
        print()
        print("Press key for note {0:3}: {1} " .format(note, name), end="")
        sys.stdout.flush()
        self.line_input.pause()
        try:
            key_name = await self.input_device.get_key()
            if key_name is None:
                return
            print(" [{}]".format(key_name))
        finally:
            self.line_input.resume()
        self.saved = False
        self.play_note(note)
        if key_name not in self.keymap:
            self.keymap.add_section(key_name)
        self.keymap[key_name]["note"] = str(note)
        defaults = self.keymap["defaults"]
        for setting in ("channel", "velocity"):
            value = self.preset.settings.get(setting)
            if value is None:
                try:
                    del self.keymap[key_name][setting]
                except KeyError:
                    pass
                continue
            if setting in defaults and defaults[setting] != str(value):
                self.keymap[key_name][setting] = str(value)

    async def preset_menu(self):
        """Preset menu"""
        preset = await self.select_preset(initial=False)
        if preset is None:
            return
        print()
        print("Selected preset:", preset.name)
        self.preset = preset

    async def save_menu(self):
        """Save menu"""
        print()
        default_fn = self.args.keymap_wizard
        filename = None
        while not filename:
            answer = await self.ask("File name: [{}] > ".format(default_fn))
            if answer:
                filename = answer
            else:
                filename = default_fn
        if os.path.exists(filename):
            answer = await self.ask("File exists, overwrite? [y/N] > ")
            if answer and answer.lower() not in ("y", "yes"):
                return
        try:
            with open(filename, "wt") as out_file:
                self.keymap.write(out_file)
        except OSError as err:
            print("Cannot save:", err)
            return
        self.saved = True

    async def main_menu(self):
        """Main menu."""
        while True:
            OPTIONS = [
                    "Show current bindings",
                    "Unbind key",
                    "Change/add binding",
                    "Change current preset",
                    "Save",
                    ]
            ans = await self.select_item(OPTIONS, "Select:")
            if ans is None:
                if self.saved:
                    return
                answer = await self.ask(
                        "Changes not saved. Are you sure? [y/N] > ")
                if answer and answer.lower() in ("y", "yes"):
                    return
                else:
                    continue
            if ans == 0:
                await self.show_bindings()
            elif ans == 1:
                await self.unbind_menu()
            elif ans == 2:
                await self.bind_menu()
            elif ans == 3:
                await self.preset_menu()
            elif ans == 4:
                await self.save_menu()

    async def run(self):
        await self.line_input.start()
        try:
            device = await self.select_device()
            if device is None:
                return
            print()
            print("Selected device:", device.name)
            self.input_device = device
            preset = await self.select_preset(initial=(not self.saved))
            if preset is None:
                return
            print()
            print("Selected preset:", preset.name)
            self.preset = preset
            if not self.saved:
                await self.configure_from_preset()
            await self.main_menu()
        finally:
            self.line_input.stop()

def keymap_wizard(args, loop, input_devices, player):
    """Build or edit a keymap file."""
    wizard = KeymapWizard(args, loop, input_devices, player)
    loop.run_until_complete(wizard.run())

