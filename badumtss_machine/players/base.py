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

"""Common MIDI player code."""

class PlayerError(Exception):
    """Raised on a player error."""

class PlayerLoadError(Exception):
    """Raised when player cannot be loaded."""

class UnknownPlayerTypeError(Exception):
    """Raised when a config section does not describe a known player type."""

class Player(object):
    """Base class for all MIDI players."""
    def __init__(self, config, section, main_loop):
        self.main_loop = main_loop

    def start(self):
        """Prepare the synthesizer for MIDI event processing."""
        pass

    def stop(self):
        """Shut down the synthesizer after MIDI event processing."""
        pass

    def note_on(self, channel, note, velocity):
        """Process the 'note on' MIDI event."""
        raise NotImplementedError

    def note_off(self, channel, note, velocity):
        """Process the 'note off' MIDI event."""
        return NotImplemented

class RawMidiPlayer(Player):
    """Base class for players that use raw MIDI messages."""
    def send(self, midi_bytes):
        """Send a MIDI message to the synthesizer."""
        raise NotImplementedError
    def note_on(self, channel, note, velocity):
        """Send the 'note on' MIDI message."""
        self.send([
                   0x90 | ((channel - 1) & 0x0f),
                   note & 0x7f,
                   velocity & 0x7f,
                   ])
    def note_off(self, channel, note, velocity):
        """Send the 'note off' MIDI message."""
        self.send([
                   0x80 | ((channel - 1) & 0x0f),
                   note & 0x7f,
                   velocity & 0x7f,
                   ])
