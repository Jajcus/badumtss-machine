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

"""Midi messages abstraction."""

from abc import ABCMeta
from collections import namedtuple

class MidiMessage(metaclass=ABCMeta):
    __slots__ = ()
    def get_bytes(self):
        raise NotImplementedError

@MidiMessage.register
class NoteOn(namedtuple("NoteOn", "channel note velocity")):
    __slots__ = ()
    def get_bytes(self):
        return bytes([
                      0x90 | ((self.channel - 1) & 0x0f),
                      self.note & 0x7f,
                      self.velocity & 0x7f
                      ])

@MidiMessage.register
class NoteOff(namedtuple("NoteOff", "channel note velocity")):
    __slots__ = ()
    def get_bytes(self):
        return bytes([
                      0x80 | ((self.channel - 1) & 0x0f),
                      self.note & 0x7f,
                      self.velocity & 0x7f
                      ])
