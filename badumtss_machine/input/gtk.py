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
from collections import namedtuple, defaultdict
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
import cairo

from .base import EventHandler, BaseInputDevice
from .. import control

logger = logging.getLogger("input.gtk")

# ___##__##______##__##__##___
# ___##__##______##__##__##___
# ___##__##______##__##__##___
# ___##__##______##__##__##___
# ____________________________
# ____________________________
#"00011223344455566775899aabbb"
#"000022224444555577779999bbbb"
PIANOKEYS = [
        [0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5, 5,
         5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 11],
        [0, 0, 0, 0, 2, 2, 2, 2, 4, 4, 4, 4, 5, 5,
         5, 5, 7, 7, 7, 7, 9, 9, 9, 9, 11, 11, 11, 11]
        ]
PIANOKEYS_LEN = len(PIANOKEYS[0])
assert len(PIANOKEYS[0]) == len(PIANOKEYS[1])

KEY_WIDTH = 32
WHITE_KEY_LENGTH = 100
KEY_RATIO = 0.6
BLACK_KEY_LENGTH = KEY_RATIO * WHITE_KEY_LENGTH

CH_BUTTON_SIZE = 16

KeyEvent = namedtuple("KeyEvent", "keyval on")
MouseClickEvent = namedtuple("MouseClickEvent", "key on")

class KeyEventHandler(EventHandler):
    def interpret_event(self, event):
        self._event = event
        if event.on:
            return "on"
        else:
            return "off"

class MouseClickEventHandler(KeyEventHandler):
    def get_note(self):
        try:
            return self._event.key
        except AttributeError as err:
            logger.debug("get_note:", exc_info=True)
            return 0

class GtkInputWindow(BaseInputDevice):
    CSS = """
        .channel-button { padding: 2; }
    """
    _windows_opened = 0
    def __init__(self, config, section, main_loop, window_name):
        self.name = "GTK ({})".format(section)
        self._window = None
        self._done = False
        self._event_map = {}
        self._queue = asyncio.Queue()
        self._gtk_event_handlers = {}
        self._keys_pressed = set()
        self._buttons_pressed = set()
        self._notes_pressed = defaultdict(set)
        self._scroll_set = False
        self._kb_canvas = None
        BaseInputDevice.__init__(self, config, section, main_loop)
        self._create_window(window_name)
        self._window.show_all()
        GtkInputWindow._windows_opened += 1
        self._window.connect("delete-event", self._window_closed)

    def _create_window(self, window_name):
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(self.CSS.encode("utf-8"))
        self._window = Gtk.Window(title=window_name)
        context = self._window.get_style_context()
        context.add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        swindow = Gtk.ScrolledWindow()
        swindow.set_size_request(KEY_WIDTH * 14, WHITE_KEY_LENGTH)
        swindow.set_hexpand(True)
        swindow.set_vexpand(False)
        swindow.set_policy(Gtk.PolicyType.ALWAYS, Gtk.PolicyType.NEVER)
        swindow.set_overlay_scrolling(False)
        self._window.set_default_size(KEY_WIDTH * 14, WHITE_KEY_LENGTH)
        viewport = Gtk.Viewport()
        button = Gtk.RadioButton.new_with_label(None, label="1")
        self._ch_buttons = [button] + [
                Gtk.RadioButton.new_with_label_from_widget(button,
                                                           str(i))
                for i in range(2, 17)]
        for button in self._ch_buttons:
            button.props.draw_indicator = False
            context = button.get_style_context()
            context.add_class("channel-button")
            context.add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            top_box.add(button)
        self._kb_canvas = Gtk.DrawingArea()
        self._kb_canvas.set_size_request(KEY_WIDTH * 75, WHITE_KEY_LENGTH)
        box.add(top_box)
        box.add(swindow)
        swindow.add(viewport)
        viewport.add(self._kb_canvas)
        self._window.add(box)
        size = self._window.get_size()
        hints = Gdk.Geometry()
        hints.min_width = size.width
        hints.max_width = size.width - KEY_WIDTH * 14 + KEY_WIDTH * 75
        hints.min_height = size.height
        hints.max_height = size.height
        self._window.set_geometry_hints(self._window,
                                        hints,
                                        Gdk.WindowHints.MIN_SIZE
                                        | Gdk.WindowHints.MAX_SIZE)
        self._kb_canvas.connect("draw", self._draw_keyboard)
        vadj = swindow.get_hadjustment()
        vadj.connect("changed", self._configure_scrolling)
        self._kb_canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                                   | Gdk.EventMask.BUTTON_RELEASE_MASK
                                   | Gdk.EventMask.LEAVE_NOTIFY_MASK
                                   | Gdk.EventMask.POINTER_MOTION_MASK)

    def _configure_scrolling(self, vadj):
        if not self._scroll_set:
            vadj.set_value(KEY_WIDTH * 28)
            self._scroll_set = True

    def _draw_keyboard(self, canvas, cr):

        # unit = one white key
        cr.scale(KEY_WIDTH, WHITE_KEY_LENGTH)

        cr.set_line_width(0.05)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.rectangle(12, 0, 52, 1)
        cr.fill()
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.rectangle(0, 0, 12, 1)
        cr.fill()
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.rectangle(64, 0, 75, 1)
        cr.fill()

        cr.select_font_face("sans-serif")
        matrix = cairo.Matrix(0.3, 0, 0, 0.3 * (KEY_WIDTH / WHITE_KEY_LENGTH))
        cr.set_font_matrix(matrix)
        for i in range(0, 75):
            cr.set_source_rgb(0.0, 0.0, 0.0)
            cr.move_to(i, 0)
            cr.rel_line_to(0, 1)
            cr.stroke()
            if (i % 7) in (0, 1, 3, 4, 5) and i < 74:
                cr.rectangle(i + 0.75, 0, 0.5, KEY_RATIO)
                cr.fill()
            octave = i // 7 - 2
            name = "CDEFGAB"[i % 7] + str(octave)
            cr.move_to(i + 0.05, 0.95)
            if name != "C3":
                cr.set_source_rgb(0.75, 0.75, 0.75)
            cr.show_text(name)

        return False

    def load_keymap(self):
        """Process `self.keymap_config` ConfigParser object to build internal
        input event to EventHandler object mapping.
        """
        if "MOUSE" not in self.keymap_config:
            self.keymap_config.add_section("MOUSE")
        for section in self.keymap_config:
            if section == "MOUSE":
                handler_class = MouseClickEventHandler
                ev_type = MouseClickEvent
                keyval = None
                if "note" not in self.keymap_config[section]:
                    self.keymap_config[section]["note"] = "varies"
            else:
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
        if not self._window:
            return
        for event in "key-press-event", "key-release-event":
            h_id = self._window.connect(event, self._key_event_handler)
            self._gtk_event_handlers[event] = h_id
        h_id = self._kb_canvas.connect("button-press-event",
                                       self._button_press_event_handler)
        self._gtk_event_handlers["button-press-event"] = h_id
        h_id = self._kb_canvas.connect("button-release-event",
                                       self._button_release_event_handler)
        self._gtk_event_handlers["button-release-event"] = h_id
        h_id = self._kb_canvas.connect("leave-notify-event",
                                       self._leave_notify_event_handler)
        self._gtk_event_handlers["leave-notify-event"] = h_id
        h_id = self._kb_canvas.connect("motion-notify-event",
                                       self._motion_notify_event_handler)
        self._gtk_event_handlers["motion-notify-event"] = h_id
        self._done = False

    def stop(self):
        """Stop processing events."""
        if not self._window:
            return
        for event in "key-press-event", "key-release-event":
            h_id = self._gtk_event_handlers.pop(event, None)
            if h_id is not None:
                self._window.disconnect(h_id)
        for event in ("button-press-event", "button-release-event",
                        "leave-notify-event", "motion-notify-event"):
            h_id = self._gtk_event_handlers.pop(event, None)
            if h_id is not None:
                self._kb_canvas.disconnect(h_id)
        self._done = True
        self._queue.put_nowait(None)
        self._queue = asyncio.Queue() # clear queue

    def _window_closed(self, window, event):
        self.stop()
        if GtkInputWindow._windows_opened > 0:
            GtkInputWindow._windows_opened -= 1
        self._window = None

    def _pointer_to_note(self, gdk_event):
        pos = int(gdk_event.x * 4 / KEY_WIDTH)
        row = int(gdk_event.y > BLACK_KEY_LENGTH)
        octave = int(gdk_event.x / (KEY_WIDTH * 7))
        return 12 * octave + PIANOKEYS[row][pos % PIANOKEYS_LEN]

    def _button_press_event_handler(self, canvas, gdk_event):
        self._buttons_pressed.add(gdk_event.button)
        note = self._pointer_to_note(gdk_event)
        if note not in self._notes_pressed[gdk_event.button]:
            self._notes_pressed[gdk_event.button].add(note)
            event = MouseClickEvent(key=note, on=True)
            self._queue.put_nowait(event)

    def _button_release_event_handler(self, canvas, gdk_event):
        self._buttons_pressed.discard(gdk_event.button)
        notes = set(self._notes_pressed[gdk_event.button])
        self._notes_pressed[gdk_event.button].clear()
        for note in notes:
            event = MouseClickEvent(key=note, on=False)
            self._queue.put_nowait(event)

    def _motion_notify_event_handler(self, canvas, gdk_event):
        note = self._pointer_to_note(gdk_event)
        for button in self._buttons_pressed:
            for act_note in list(self._notes_pressed[button]):
                if act_note != note:
                    self._notes_pressed[button].clear()
                    event = MouseClickEvent(key=act_note, on=False)
                    self._queue.put_nowait(event)
            if note not in self._notes_pressed[button]:
                self._notes_pressed[button].add(note)
                event = MouseClickEvent(key=note, on=True)
                self._queue.put_nowait(event)

    def _leave_notify_event_handler(self, canvas, gdk_event):
        self._buttons_pressed.clear()
        sets = self._notes_pressed.values()
        if not sets:
            return
        notes = set.union(*sets)
        self._notes_pressed.clear()
        for note in notes:
            event = MouseClickEvent(key=note, on=False)
            self._queue.put_nowait(event)

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
                if self._windows_opened == 0:
                    self._windows_opened = None
                    return control.Quit()
                raise StopAsyncIteration
            if event is None:
                continue
            logger.debug("event: %r", event)
            if isinstance(event, MouseClickEvent):
                key = (MouseClickEvent, None)
            else:
                key = (type(event), event[0])
            handler = self._event_map.get(key)
            if handler:
                msg = handler.translate(event)
                if msg is not None:
                    return msg

    async def get_key(self):
        """Read single keypress from the device."""
        if not self._window:
            return None
        self._window.present()
        self.start()
        try:
            while True:
                logger.debug("key_key")
                if not self._window:
                    return None
                event = await self._queue.get()
                logger.debug("event: %r", event)
                if event is None:
                    continue
                if isinstance(event, KeyEvent):
                    if event.on:
                        return Gdk.keyval_name(event.keyval)
                    else:
                        logger.debug("ignorning key release")
                logger.debug("ignorning unknown event")
        finally:
            self.stop()

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
