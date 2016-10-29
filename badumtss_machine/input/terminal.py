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
import curses
import logging
import os
import sys
import termios

from .base import EventHandler, BaseInputDevice, InputDeviceLoadError

logger = logging.getLogger("input.terminal")

class CursesKeyHandler(EventHandler):
    def interpret_event(self, event):
        return "on"

class TerminalDevice(BaseInputDevice):
    name = "Terminal"
    def __init__(self, config, section, main_loop):
        self._done = False
        self._stdscr = None
        self._queue = asyncio.Queue()
        self._event_map = {}
        self._saved_tc_attrs = None
        self._curses_tc_attrs = None
        BaseInputDevice.__init__(self, config, section, main_loop)

    def __del__(self):
        if not self._done:
            self.stop()
        if self._stdscr:
            self._finalize_terminal()

    def load_keymap(self):
        """Process `self.keymap_config` ConfigParser object to build internal
        input event to EventHandler object mapping.
        """
        for section in self.keymap_config:
            if len(section) == 1:
                key = section
            elif section.startswith("KEY_"):
                key = section
            else:
                continue
            settings = self.keymap_config[section]
            handler = CursesKeyHandler(self, section, settings)
            self._event_map[key] = handler
        logger.debug("event map: %r", self._event_map)

    def _initialize_terminal(self):
        """Initialize curses terminal."""
        logger.debug("initializing terminal...")

        # save current output flags
        stdin = sys.stdin.fileno()
        self._saved_tc_attrs = termios.tcgetattr(stdin)

        # standard curses init
        self._stdscr = curses.initscr()
        self._stdscr.nodelay(True)
        curses.noecho()
        curses.cbreak()

        # hack: prevent curses from touching the screen
        # we need input only
        self._stdscr.untouchwin()
        self._stdscr.clearok(False)

        # undo terminal output settings changes made by curses
        attrs = termios.tcgetattr(stdin)
        attrs[1] = self._saved_tc_attrs[1]
        termios.tcsetattr(stdin, termios.TCSANOW, attrs)
        self._curses_tc_attrs = attrs

        self.main_loop.add_reader(stdin, self._reader)

    def _finalize_terminal(self):
        """Finalize curses terminal."""
        if not self._stdscr:
            return
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        self._stdscr = None

    def start(self):
        """Start terminal input."""
        self._initialize_terminal()
        self.main_loop.add_reader(sys.stdin.fileno(), self._reader)
        self._done = False

    def stop(self):
        """Stop processing events."""
        if self._done:
            return
        logger.debug("restoring terminal...")
        self._done = True
        self.main_loop.remove_reader(sys.stdin.fileno())
        self._finalize_terminal()

    async def get_key(self):
        """Read single keypress from the device."""
        stdin = sys.stdin.fileno()
        if not self._stdscr:
            self._initialize_terminal()
        else:
            termios.tcsetattr(stdin, termios.TCSANOW, self._curses_tc_attrs)
        self._done = False
        self.main_loop.add_reader(stdin, self._reader)
        try:
            key = await self._queue.get()
        finally:
            termios.tcsetattr(stdin, termios.TCSANOW, self._saved_tc_attrs)
            self._done = True
            self.main_loop.remove_reader(stdin)
        return key

    def _reader(self):
        """Handle terminal input."""
        logger.debug("input pending")
        if self._done:
            logger.debug("   ...but we are done, flushing")
            os.read(sys.stdin.fileno())
            return
        try:
            key = self._stdscr.getkey()
        except curses.error:
            logger.debug("no input")
            return
        self.main_loop.create_task(self._queue.put(key))

    async def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            key = await self._queue.get()
            if self._done:
                raise StopAsyncIteration
            if key is None:
                logger.debug("no key?")
                continue
            logger.debug("key: %r", key)
            handler = self._event_map.get(key)
            if handler:
                msg = handler.translate(key)
                if msg is not None:
                    return msg
            else:
                logger.debug("no handler for %r", key)

def input_device_factory(config, section, main_loop):
    if not os.isatty(sys.stdin.fileno()):
        raise InputDeviceLoadError("stdin is not a TTY")
    yield TerminalDevice(config, section, main_loop)
