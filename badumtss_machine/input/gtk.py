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
from collections import namedtuple
import logging
import signal

import gbulb

import gi
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
except (AttributeError, ValueError) as err:
    raise ImportError(err)
from gi.repository import Gtk, Gdk, GLib

from .base import EventHandler, BaseInputDevice

logger = logging.getLogger("input.gtk")

KeyEvent = namedtuple("KeyEvent", "keyval on")

class KeyEventHandler(EventHandler):
    def interpret_event(self, event):
        if event.on:
            return "on"
        else:
            return "off"

class GtkInputWindow(BaseInputDevice):
    _windows_opened = 0
    def __init__(self, config, section, main_loop, window_name):
        self.name = "GTK ({})".format(section)
        self._done = False
        self._event_map = {}
        self._queue = asyncio.Queue()
        self._gtk_event_handlers = {}
        self._keys_pressed = set()
        BaseInputDevice.__init__(self, config, section, main_loop)
        self._window = Gtk.Window(title=window_name)
        self._window.show_all()
        GtkInputWindow._windows_opened += 1
        self._window.connect("delete-event", self._window_closed)

    def load_keymap(self):
        """Process `self.keymap_config` ConfigParser object to build internal
        input event to EventHandler object mapping.
        """
        for section in self.keymap_config:
            handler_class = KeyEventHandler
            ev_type = KeyEvent
            keyval = Gdk.keyval_from_name(section)
            if keyval == Gdk.KEY_VoidSymbol:
                continue
            key = (ev_type, keyval)
            settings = self.keymap_config[section]
            handler = handler_class(self, key, settings)
            self._event_map[key] = handler

    def start(self):
        """Prepare device for processing events."""
        for event in "key-press-event", "key-release-event":
            h_id = self._window.connect(event, self._key_event_handler)
            self._gtk_event_handlers[event] = h_id

    def stop(self):
        """Stop processing events."""
        for event in "key-press-event", "key-release-event":
            h_id = self._gtk_event_handlers.pop(event, None)
            if h_id is not None:
                self._window.disconnect(h_id)
        self._done = True
        self._queue.put_nowait(None)

    def _window_closed(self, window, event):
        self.stop()
        if self._windows_opened > 0:
            self._windows_opened -= 1
        if not self._windows_opened:
            self.main_loop.call_soon(self.main_loop.stop)

    def _key_event_handler(self, window, gdk_event):
        keyval = gdk_event.keyval
        pressed = (gdk_event.type == Gdk.EventType.KEY_PRESS)
        if pressed:
            if keyval in self._keys_pressed:
                # ignore auto-repeat events
                return
            else:
                self._keys_pressed.add(keyval)
        else:
            self._keys_pressed.discard(keyval)
        # save it in own type, as GdkEvent object seem to break outside
        # of this handler
        event = KeyEvent(keyval=keyval, on=pressed)
        self._queue.put_nowait(event)

    async def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            event = await self._queue.get()
            if self._done:
                raise StopAsyncIteration
            if event is None:
                continue
            logger.debug("event: %r", event)
            handler = self._event_map.get((type(event), event[0]))
            if handler:
                msg = handler.translate(event)
                if msg is not None:
                    return msg

    async def get_key(self):
        """Read single keypress from the device."""
        while True:
            if not self._window:
                return None
            event = await self._queue.get()
            if event is None:
                continue
            if isinstance(event, KeyEvent) and not event.on:
                continue
            break
        return Gdk.keyval_name(key)

def _sig_handler(signum):
    """Handle SIGIT in GLib loop."""
    asyncio.get_event_loop().stop()

_sig_handler_installed = False

def initialize_input_driver(config):
    """Set up GTK main loop for use with asyncio."""
    gbulb.install(gtk=True)

def input_device_factory(config, section, main_loop):
    global _sig_handler_installed

    if not _sig_handler_installed:
        # gbulb should tak care of that
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _sig_handler,
                             signal.SIGINT)
        _sig_handler_installed = True

    name = config[section].get("window_name")
    if not name:
        if ":" in section:
            name = "Ba-Dum-Tss Machine ({})".format(section.split(":", 1)[1])
        else:
            name = "Ba-Dum-Tss Machine"
    yield GtkInputWindow(config, section, main_loop, name)
