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

import logging
import os

from configparser import ConfigParser, ExtendedInterpolation

from .. import midi

logger = logging.getLogger("input.base")

class InputDeviceError(Exception):
    """Raised on input device errors."""
    pass

class InputDeviceLoadError(InputDeviceError):
    """Raised when input device handler cannot be loaded."""
    pass

class UnknownDeviceTypeError(InputDeviceLoadError):
    """Raised when a config section does not describe a known input type."""
    pass

class EventHandler(object):
    """Process input events and translate them to MIDI or control messages."""
    def __init__(self, device, key, settings):
        self._device = device
        self._settings = settings

    def get_velocity(self):
        """Return velocity for current event."""
        return int(self._settings["velocity"])

    def get_note(self):
        """Return note for current event.
        
        Used only when note is set to 'varies' in settings."""
        return 0

    def interpret_event(self, event):
        """Intepret input event.

        Store any relevant event information for future use
        and return basic classification ("on", "off" or "ignore").
        """
        raise NotImplementedError

    def translate(self, event):
        """Process event and and translate it to a MIDI or control message as
        appropriate.

        The `event` is an opaque object to be interpreted by classes derived
        from EventHandler.
        """
        interpret_event = self.interpret_event(event)
        if interpret_event == "ignore":
            return None
        if "note" in self._settings:
            note = self._settings["note"]
            if note == "varies":
                note = self.get_note()
            else:
                note = int(note)
            channel = int(self._settings["channel"])
            velocity = self.get_velocity()
            if interpret_event == "on":
                logger.debug("  note on: %r, %r, %r", channel, note, velocity)
                return midi.NoteOn(channel, note, velocity)
            elif interpret_event == "off":
                logger.debug("  note off: %r, %r, %r", channel, note, velocity)
                return midi.NoteOff(channel, note, velocity)
        else:
            return None

class BaseInputDevice(object):
    KEYMAP_DEFAULTS = {
            "channel": "1",
            "velocity": "127",
            }
    name = "unknown"
    def __init__(self, config, section, main_loop):
        self.main_loop = main_loop
        self.config = config
        self.config_section = section
        keymap_file = config[section].get("keymap", None)
        self.keymap_config = ConfigParser(interpolation=ExtendedInterpolation(),
                                          default_section="defaults")
        self.set_keymap_defaults()
        if keymap_file:
            keymap_file = os.path.expanduser(keymap_file)
            if not self.keymap_config.read(keymap_file):
                logger.warning("Could not load keymap: %r", keymap_file)
        self.load_keymap()

    def set_keymap_defaults(self):
        """Set keymap defaults."""
        self.keymap_config["defaults"].update(self.KEYMAP_DEFAULTS)

    def load_keymap(self):
        """Process `self.keymap_config` ConfigParser object to build internal
        input event to EventHandler object mapping.
        """
        raise NotImplementedError

    def start(self):
        """Prepare device for processing events."""
        pass

    def stop(self):
        """Stop processing events and emitting messages."""
        pass

    async def get_key(self):
        """Read single keypress from the device."""
        raise NotImplementedError

    async def __aiter__(self):
        """Generate MIDI or controll messages."""
        raise NotImplementedError
