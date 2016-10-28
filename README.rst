Ba-Dum-Tss Machine
==================

Ba-Dum-Tss Machine is a little application that converts any Linux input device
into a MIDI keyboard. It was created to see if toy percussion set from a Guitar
Hero game can be used as electronic drums.

It is also an excuse for me to play with MIDI APIs and Python asyncio framework.

The code and has been written for Linux only, as it relies on Linux-specific
APIs. It should be possible to add support for other platforms, though.

It is a work in progress, with little prospect for sustained development. It
might be fun, anyway.

Requirements
------------

* Python_ 3.5

Input support:

* python-evdev_ for event devices (like game controllers)

Simple terminal input is implemented using the curses module from the standard
Python library, but it should be considered a proof of concept only.

Output support:

* JACK-Client_ Python package for output through a Jack MIDI port
* FluidSynth_ for play audio directly from the synthesizer

Usage
-----

Run the script from the source directory:

  ./badumtss-machine.py

The provided config file will be used to detect available input devices and
output interfaces. All detected output devices will be used and the first
output interface found (configuration file section order counts).

An intro sound will be played and then input events will be converted to MIDI
events or synthesizer commands.

Configuration file may need adjusting, especially the FluidSynth arguments
(audio driver and soundfont path).

Keymap Wizard
-------------

Mapping of input to MIDI events is described in keymap files referenced in the
main configuration file input sections. Instead of editing the keymap files by
hand one can use the included 'keymap wizard'.

To run the wizard, use the ``-w`` option:

  ./badumtss-machine.py -w

Note: the keymap file created must be referenced from the main configuration
file to be used.

.. _Python: http://www.python.org/
.. _python-evdev: https://pypi.python.org/pypi/evdev/
.. _JACK-Client: https://pypi.python.org/pypi/JACK-Client/
.. _FluidSynth: http://www.fluidsynth.org/
