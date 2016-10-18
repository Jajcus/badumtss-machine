#!/usr/bin/python3

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

import time
import logging
import re
import asyncio

from configparser import ConfigParser

from functools import partial
from queue import Queue, Empty

import jack
import evdev

from evdev.ecodes import EV_KEY

logger = logging.getLogger()

class JackPlayer(object):
    def __init__(self, target_ports_re=None, stopper=None):
        self._stopper = stopper
        if isinstance(target_ports_re, str):
            self._target_ports_re = re.compile(target_ports_re)
        else:
            self._target_ports_re = target_ports_re
        self._active = 0
        self._queue = Queue()
        self._logger = logging.getLogger("jack_player")
        j_logger = logging.getLogger("jack_player.jack")
        jack.set_error_function(partial(j_logger.error, "%s"))
        jack.set_info_function(partial(j_logger.info, "%s"))
        self._client = jack.Client("Badum-tss machine")
        self._client.set_shutdown_callback(self._shutdown)
        self._client.set_port_registration_callback(self._port_registration)
        self._client.set_port_rename_callback(self._port_rename)
        self._client.set_xrun_callback(self._xrun)
        self._client.set_process_callback(self._process)
        self._port = None

    def __enter__(self):
        if not self._active:
            self._client.activate()
            self._port = self._client.midi_outports.register("midi_out")
            self._connect_ports()
        self._active += 1
        return self

    def __exit__(self, e_type, value, traceback):
        self._active -= 1
        if self._active < 0:
            self._port = None
            self._client.deactivate()
            self._client.close()
        return False

    def _connect_ports(self):
        if not self._target_ports_re:
            return
        for port in self._client.get_ports(is_midi=True, is_input=True):
            match = self._target_ports_re.match(port.name)
            if match:
                self._logger.info("Connecting to %r", port.name)
                self._port.connect(port)

    def _shutdown(self, status, reason):
        self._logger.info("Jack is shutting down: %s, %s", status, reason)
        if self._stopper:
            self._stopper()

    def _port_registration(self, port, register):
        self._logger.info("port %s: %r",
                          "registered" if register else "unregistered",
                          port)
        if not port.is_midi or not port.is_input:
            return
        if not self._target_ports_re or not self._port:
            return
        match = self._target_ports_re.match(port.name)
        if match:
            self._logger.info("Connecting to %r", port.name)
            self._port.connect(port)

    def _port_rename(self, port, old, new):
        self._logger.info("port renamed: %r '%s' -> '%s'",
                          port, old, new)

    def _xrun(self, delay):
        self._logger.warning("XRUN, delay: %s microseconds", delay)

    def _process(self, frames):
        if not self._port:
            return
        self._port.clear_buffer()
        while True:
            try:
                msg = self._queue.get(False)
            except Empty:
                break
            self._port.write_midi_event(0, msg)
            self._queue.task_done()

    def note_on(self, channel, note, velocity):
        self._queue.put([
                    0x90 | ((channel - 1) & 0x0f),
                    note & 0x7f,
                    velocity & 0x7f,
                    ])

    def note_off(self, channel, note, velocity):
        self._queue.put([
                    0x80 | ((channel - 1) & 0x0f),
                    note & 0x7f,
                    velocity & 0x7f,
                    ])

class EventHandler(object):
    def __init__(self, device, settings, player):
        self._device = device
        self._settings = settings
        self._player = player
    def get_velocity(self, event):
        return int(self._settings.get("velocity", 127))
    def event_value(self, event):
        raise NotImplementedError
    def process(self, event):
        event_value = self.event_value(event)
        if event_value == "ignore":
            return
        if "note" in self._settings:
            note = int(self._settings["note"])
            channel = int(self._settings.get("channel", 1))
            velocity = self.get_velocity(event)
            if event_value == "on":
                logger.debug("  note on: %r, %r, %r", channel, note, velocity)
                self._player.note_on(channel, note, velocity)
            elif event_value == "off":
                logger.debug("  note off: %r, %r, %r", channel, note, velocity)
                self._player.note_off(channel, note, velocity)

class KeyEventHandler(EventHandler):
    def event_value(self, event):
        if event.keystate == event.key_down:
            return "on"
        elif event.keystate == event.key_up:
            return "off"
        else:
            return "ignore"

class InputDeviceHandler(object):
    def __init__(self, config, device, player):
        self.config = config
        self.device = device
        self.player = player
        self.map = {}
        self._load_config()

    def _load_config(self):
        try:
            defaults = self.config["defaults"]
        except KeyError:
            defaults = {}
        for section in self.config:
            if section.startswith("KEY_") or section.startswith("BTN_"):
                try:
                    ecode = evdev.ecodes.ecodes[section]
                except KeyError:
                    logger.warning("Unknown key name: %r", section)
                    continue
                handler_class = KeyEventHandler
                ev_type = EV_KEY
            else:
                continue
            settings = dict(defaults)
            settings.update(self.config[section])
            handler = handler_class(self.device, settings, self.player)
            self.map[ev_type, ecode] = handler

    async def handle_events(self):
        async for event in self.device.async_read_loop():
            ev_type = event.type
            ev_code = event.code
            event = evdev.categorize(event)
            logger.debug("%s: %s", self.device.fn, event)
            handler = self.map.get((ev_type, ev_code))
            if handler:
                handler.process(event)

INTRO_NOTES = [38, 38, 0, 49]

def play_intro(player):
    for note in INTRO_NOTES:
        print("#")
        if note:
            player.note_on(10, note, 127)
        time.sleep(0.2)

def main():
    logging.basicConfig(level=logging.DEBUG)
    config = ConfigParser()
    config['DEFAULT'] = {
                         "input_device": ".*",
                         "jack_connect": "",
                         }
    config.read("badumtss.conf")
    input_device_re = re.compile(config["general"]["input_device"])
    devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
    devices = [dev for dev in devices if input_device_re.match(dev.name)]
    loop = asyncio.get_event_loop()
    def stop_loop():
        loop.call_soon_threadsafe(loop.stop)
    player = JackPlayer(config["general"]["jack_connect"], stop_loop)
    dev_handlers = []
    for device in devices:
        handler = InputDeviceHandler(config, device, player)
        dev_handlers.append(handler)
    with player:
        play_intro(player)
        if not devices:
            logger.error("No input device matching %r found, exiting",
                            config["general"]["input_device"])
            return
        for handler in dev_handlers:
            asyncio.ensure_future(handler.handle_events())
        loop.run_forever()

if __name__ == "__main__":
    main()
