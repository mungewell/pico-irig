# pico-irig
Pico micropython script to produce IRIG-A/IRIG-B timecode using the PIO blocks and
minimal hardware. The IRIG waveform is 'rendered' with 2 resistors and a buffer/amp
IC.

Sister project to 'pico-timecode' (1) which uses the PIO blocks of the Pico to generate 
SMPTE timecode with minimal hardware.

The intent is to produce valid (and well synchronized) timecode from a GPSDO, using the 
NMEA/1PPS to derive true time, whilst using the 10MHz clock to also clock the Pico. In 
theory this will ensure that the timecode is kept in sync, without complicated calibration
processes/software.

For simpler applications time can be sync'ed with RTC with 1PPS output, the DS3231 for 
example.

1 - https://github.com/mungewell/pico-timecode

# how it works

As mentioned above the project leans on the PIO blocks to perform most functions of
the project, since these are much simpler processors their behaviour is much more
deterministic than the main CPU. _Rather, it's easier to write small chunks of code
which are not affected by all the things that make the CPU un-deterministic..._

The four parts are:
* Synchronisation
* FIFO
* Encoder
* Modulator

## Synchronisation

We ultimately want the output to be synchronised with another clock, for this we 
use the 1PPS input. This is used to trigger the other StateMachine to start from 
a know point in code at the correct time, via them waiting with `irq(block, 4)`
and the synchroniser clearing the interrupt at the right time with `irq(clear, 4)`.

## FIFO

This is really the heart of the project. The output IRIG stream is encoded as 100
bits (symbols) of information; containing the time value, some other data and a
some markers allowing a partner device to align with stream.

For IRIG-B this 'frame' is 1s in duration, for IRIG-A it is 100ms.

The values (and positions) for the 'data' and the 'markers' are __pre-computed__
by the CPU, and each 'frame' is pushed into a FIFO for the state machine to
use. The FIFO uses bit-pairs, where the upper bit encodes the markters ('Px', 
'P1..P9' and 'P0' at the end) and the lower bit encodes the data.

Each 'frame' starts with 'Pr' marker... the FIFO loads the bit-pair and places
these on it's output pins. Since 100 bit-pairs is not an '2^X' number it counts
the markers, and once the 11th ('P0') is output it clears the ISR so that the
coding to loading the next FIFO block is easier.

The duration of the FIFO state machine's code is 1 'frame', which is 100 'symbols' 
or 1200 clock periods.

## Encoder

Each of the bits (or bit-pairs) in the 'frame' is encoded as a 'symbol' with a 
ratio of high to low time:

* data-0: 20% high, 80% low
* data-1: 50$ high, 50% low
* marker: 80% high, 20% low

The encoder state machine monitors the outputs from the FIFO, and uses these to
produce the modulation.

The duration of the state machine's code is one 'symbol', ie 12 clock periods.

## Modulator

For IRIG we actually want a Amplitude-Shift-Keying output, where a 1KHz signal
is modulated with high and low amplitudes, directly relating to the output of
the modulator.

This runs synchronised with the encoder, and (ab)uses the pull-up/down resistors
of the PIO GPIO output to produce intermediate values/analogue voltages.

The duration of the state machine's code is one 'symbol', ie 12 clock periods.
