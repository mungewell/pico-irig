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
