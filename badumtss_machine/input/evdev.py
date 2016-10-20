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
import math

import evdev
from evdev.ecodes import EV_KEY, EV_ABS

from .base import EventHandler, BaseInputDevice

logger = logging.getLogger("input.evdev")

class KeyEventHandler(EventHandler):
    def interpret_event(self, event):
        if event.keystate == event.key_down:
            return "on"
        elif event.keystate == event.key_up:
            return "off"
        else:
            return "ignore"

class AbsEventHandler(EventHandler):
    def __init__(self, device, key, settings, player):
        super().__init__(device, key, settings, player)
        self._last_value = None
        self._last_value_ts = None
        self._min = None
        self._max = None
        self._thres_low = None
        self._thres_high = None
        self._velocity = None
        self._velocity_coeff = float(settings.get("velocity_coeff", 2.0))
        etype, ecode  = key
        abs_caps = device.device.capabilities(absinfo=True)[etype]
        for code, absinfo in abs_caps:
            if code == ecode:
                break
        else:
            logger.error("Cannot retrieve absinfo for %r", ecode)
            return
        self._min = absinfo.min
        self._max = absinfo.max
        self._range = absinfo.max - absinfo.min
        def val_to_abs(val):
            if not val.endswith("%"):
                return float(val)
            pcent = float(val[:-1])
            return self._min + pcent * (self._max - self._min) / 100.0
        if "thres_low" in settings:
            self._thres_low = val_to_abs(settings["thres_low"])
        else:
            self._thres_low = self._min
        if "thres_high" in settings:
            self._thres_high = val_to_abs(settings["thres_high"])
        else:
            self._thres_high = self._max

    def get_velocity(self):
        if self._velocity is not None:
            return self._velocity
        else:
            return super().get_velocity()

    def _compute_velocity(self, value, event_ts):
        if not self._range:
            self._velocity = None
            return
        rel_change = float(value - self._last_value) / self._range
        if rel_change > 0 and self._last_value < self._thres_low:
            # the low value could be collected before the move started
            velocity = math.inf
        elif rel_change < 0 and self._last_value > self._thres_high:
            # the high value can be collected before the move started
            velocity = math.inf
        else:
            time_change = event_ts - self._last_value_ts
            velocity = abs(rel_change / time_change)
        logger.debug("unscaled velocity: %f", velocity)
        if velocity != math.inf:
            velocity = int(velocity * self._velocity_coeff)
        if velocity < 0:
            self._velocity = 0
        elif velocity > 127:
            self._velocity = 127
        else:
            self._velocity = velocity

    def interpret_event(self, event):
        value = event.event.value
        event_ts = event.event.timestamp()
        if self._last_value is None:
            result = "ignore"
        elif value > self._last_value:
            # rising
            if value > self._thres_high and self._last_value < self._thres_high:
                result = "on"
                self._compute_velocity(value, event_ts)
            else:
                result = "ignore"
        elif value < self._last_value:
            # falling
            if value < self._thres_low and self._last_value > self._thres_low:
                result = "off"
                self._compute_velocity(value, event_ts)
            else:
                result = "ignore"
        else:
            result = "ignore"
        self._last_value = value
        self._last_value_ts = event_ts
        return result

class EventDevice(BaseInputDevice):
    def __init__(self, config, section, main_loop, player, device):
        BaseInputDevice.__init__(self, config, section, main_loop, player)
        self.device = device
        self._event_map = {}
        self._load_handlers()

    def _load_handlers(self):
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
            elif section.startswith("ABS_"):
                try:
                    ecode = evdev.ecodes.ecodes[section]
                except KeyError:
                    logger.warning("Unknown axis name: %r", section)
                    continue
                handler_class = AbsEventHandler
                ev_type = EV_ABS
            else:
                continue
            key = (ev_type, ecode)
            settings = dict(defaults)
            settings.update(self.config[section])
            handler = handler_class(self, key, settings, self.player)
            self._event_map[key] = handler

    async def handle_events(self):
        async for event in self.device.async_read_loop():
            ev_type = event.type
            ev_code = event.code
            event = evdev.categorize(event)
            handler = self._event_map.get((ev_type, ev_code))
            if handler:
                handler.play(event)

def event_device_factory(config, section, main_loop, player):
    try:
        name = config[section]["name"]
    except KeyError:
        name = ".*"
    input_device_re = re.compile(name)
    devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
    devices = [dev for dev in devices if input_device_re.match(dev.name)]
    if not devices:
        logger.debug("[%s]: no device matches name %r", section, name)
        return
    for device in devices:
        try:
            handler = EventDevice(config, section, main_loop, player, device)
        except Exception as err:
            logger.warning("[%s]: cannot load event device: %s", section, err)
            logger.debug("Exception:", exc_info=True)
            continue
        yield handler
