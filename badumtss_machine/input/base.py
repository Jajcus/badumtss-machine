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

logger = logging.getLogger("input.base")

class EventHandler(object):
    """Process input events passing them to the MIDI player."""
    def __init__(self, device, key, settings, player):
        self._device = device
        self._settings = settings
        self._player = player

    def get_velocity(self):
        """Return velocity for current event."""
        return int(self._settings.get("velocity", 127))

    def interpret_event(self, event):
        """Intepret input event.

        Store any relevant event information for future use
        and return basic classification ("on", "off" or "ignore").
        """
        raise NotImplementedError

    def play(self, event):
        """Process event and pass it to the MIDI player as appropriate.

        The `event` is an opaque object to be interpreted by classes derived
        from EventHandler.
        """
        interpret_event = self.interpret_event(event)
        if interpret_event == "ignore":
            return
        if "note" in self._settings:
            note = int(self._settings["note"])
            channel = int(self._settings.get("channel", 1))
            velocity = self.get_velocity()
            if interpret_event == "on":
                logger.debug("  note on: %r, %r, %r", channel, note, velocity)
                self._player.note_on(channel, note, velocity)
            elif interpret_event == "off":
                logger.debug("  note off: %r, %r, %r", channel, note, velocity)
                self._player.note_off(channel, note, velocity)

class BaseInputDevice(object):
    def __init__(self, config, section, main_loop, player):
        self.main_loop = main_loop
        self.config = config
        self.config_section = section
        self.player = player

    def start(self):
        """Start processing events."""
        raise NotImplementedError

    def stop(self):
        """Stop processing events."""
        raise NotImplementedError
