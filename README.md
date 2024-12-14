# pico-irig
Pico micropython script to produce IRIG-A/IRIG-B timecode using the PIO blocks and
minimal hardware. The IRIG waveform is 'rendered' with 2 resistors and a buffer/amp
IC.

Sister project to 'pico-timecode' (1) which uses the PIO blocks of the Pico to generate 
SMPTE timecode with minimal hardware.

The intent is to produce valid (and well synchronized) timecode from a GPSDO, using the 
NMEA/1PPS to derive true time, whilst using the 10MHz clock to also clock the Pico.

In theory this will ensure that the timecode is kept in sync, without complicated 
calibration processes/software. For simpler applications time can be sync'ed with 
RTC with 1PPS output, the DS3231 for example.

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

## Synchroniser

We ultimately want the output to be synchronised with another clock, for this we 
use the 1PPS input.

This is used to trigger the other state machine to start from 
a know point in code at the correct time, via them waiting with `irq(block, 4)`
and the synchroniser clearing the interrupt at the right time with `irq(clear, 4)`.

_The Synchroniser is 'one and done', but I may let it continue to run so that
the timing of the interrupts can be monitored by the CPU._

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
or 1200 SM clock periods.

## Encoder

Each of the bits (or bit-pairs) in the 'frame' is encoded as a 'symbol' with a 
ratio of high to low time:

* data-0: 20% high, 80% low
* data-1: 50$ high, 50% low
* marker: 80% high, 20% low

The Encoder state machine monitors the outputs from the FIFO, and uses these to
produce the modulation.

The duration of the Encoder state machine's code is one 'symbol', ie 12 SM clock periods.

## Modulator

For IRIG we actually want a Amplitude-Shift-Keying output, where a 1KHz signal
is modulated with high and low amplitudes, directly relating to the output of
the modulator.

This runs synchronised with the encoder, and (ab)uses the pull-up/down resistors
of the GPIO outputs to produce intermediate values/analogue voltages.

The duration of the Modulator state machine's code is one 'symbol', ie 12 SM clock periods.

# The 'analogue' output

The Pico __does not__ have an analogue output, one which can be programmed to varying
voltages - as would normally be used for generating a sine wave. Some advanced 
projects would include a DAC IC or implemented with a resistor ladder.

Instead this project (ab)uses two digital GPIOs to _fake_ one. 

By using the two GPIOs __either__ as outputs (driving 0V or 3.3V) or as inputs (with 
pull up or pull down resistors), we can render intermediate levels. Two series resistors 
are connected between the two outputs, and the center point is connected to a buffer.

The value of the resistors set the amplitude of the 'low' sine, the absolute 
value is not too critcal and 33K seems to be OK. _The values of the internal
pull-up/pull-down resistors can vary between 50K and 80K._

Note: we could use a square wave and filter it down to a sine, but a square wave
contains a lot of harmonics (with 3rd being around -12dB). Using this 'modified 
square' output reduces the harmonics (with 3rd being around -30dB).

# Clocking

Obviously the desire for a stable/precision clock output depends on how the Pico
is clocked itself. For best precision the Pico should be clocked from the 10MHz
GPSDO, with the the 1PPS output triggering the state machine to start.

We change the CPU clock to 120MHz and the individual state machine(s) are (mostly) 
clocked from 12KHz, this gives an interger divider (to reduce jitter). The 
exception to this is the Synchroniser, which needs to be clocked at 10MHz as 
the 1PPS from the GPSDO is likely only a single 10MHz clock period.

The Pico offers the ability to align the clock dividers, so that they start
counting at the __same instant__.

_Not implemented yet, but the plan is to use a 'first stage' synchroniser at 
full CPU clock rate, and re-align the clock dividers to the very moment that 
1PPS changes... the normal state machines would then be run on the following 
1PPS occurance._

I chose to use 12KHz (or 120KHz for IRIG-A) as this matches nicely with the 
Modulator use of 'side set' (which limits the code's 'additional delay' macro)
whilst still resulting in workable code length. The PIO code space is actually
__100%__ full....

12KHz, 120KHz, and 120MHz also all work nicely if/when the stock XTAL (12MHz) is
replaced with 10MHz, and the CPUs SYS-Clk PLL can be adjusted:
```
$ python3 vcocalc.py --input 10 120
Requested: 120.0 MHz
Achieved: 120.0 MHz
REFDIV: 1
FBDIV: 144 (VCO = 1440.0 MHz)
PD1: 6
PD2: 2
```

Note: Custom 'micropython.uf2' can be loaded to ensure USB and UART work at 
the correct speed(s).
