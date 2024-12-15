import utime
from machine import Pin, I2C
from ds3231 import DS3231

rtc = I2C(0, sda=Pin(16), scl=Pin(17))
pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)

ds = DS3231(rtc)
ds.square_wave(freq=ds.FREQ_1)

gm = utime.gmtime(utime.time())
print("Current UTC", gm)

# set RTC excluding Day-of-Week, and Day-of-Year
ds.datetime(gm[:6])

for i in range(10):
    print("PPS", pps.value(), ds.datetime())
    utime.sleep(0.25)

